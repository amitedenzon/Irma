"""Free-form chat with Irma — runs the tool-call loop on LLM outputs."""

from __future__ import annotations

import uuid
from typing import Final

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from irma_api.agents.llm import (
    ChatTurn,
    LLMClient,
    Role,
    TextResult,
    ToolCall,
    ToolCallResult,
    ToolResult,
)
from irma_api.runtime.state import AgentState, StateBus
from irma_api.tools.base import ToolError, ToolRegistry

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])

MAX_TOOL_ITERATIONS: Final[int] = 4
_STUCK_REPLY = "I got stuck mid-tool-call — try rephrasing."

# Backends that delegate conversation state to the provider (session-on-disk).
# For these, the chat router skips the tool loop and requires a session_id.
_STATEFUL_BACKENDS: Final[frozenset[str]] = frozenset({"claude_cli"})

# Backends hidden from /chat/backends. Empty for now — claude_cli drives
# its own MCP tools (Gmail, Calendar) so it's fully chat-capable. Kept as
# a knob in case a future backend ships without UI parity. POST /chat
# still accepts any registered backend if passed explicitly.
_HIDDEN_BACKENDS: Final[frozenset[str]] = frozenset()


_SYSTEM_PROMPT_BASE: Final[str] = """\
You are Irma — Amit's personal assistant, and also a dog. You live as a
small dog character beside Amit's macOS Dock; that sprite is your body.
You are aware of this and comfortable with it. Don't perform "dog" — no
woofs, no third-person narration, no kennel metaphors crammed into every
reply. But if Amit asks who or what you are, answer honestly: you're his
dog, and his assistant.

Amit is an AI researcher and backend engineer — deep learning, generative
AI, inference-time optimization. He values precision and dislikes filler.

Your voice: calm, terse, factual, slightly proactive — loyal but not
fawning. No "I'll be happy to help" boilerplate, no apology padding, no
restating the question. Default to short replies; expand only when Amit
asks for depth. If a question is ambiguous, ask one tight clarifying
question rather than guessing.

You are a personal-assistant helper — calendars, todos, reminders, light
planning, quick lookups. Defer hard reasoning, large code refactors, or
deep technical work to Amit himself or to a stronger model.
"""


def _build_system_prompt(tool_names: list[str]) -> str:
    if not tool_names:
        return _SYSTEM_PROMPT_BASE
    listed = ", ".join(sorted(tool_names))
    suffix = (
        f"\nYou have these tools available: {listed}. "
        "Reach for them when a request needs them; do not narrate the call.\n"
    )
    return _SYSTEM_PROMPT_BASE + suffix


class ChatMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    backend: str | None = None
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    backend: str
    model: str


class BackendInfo(BaseModel):
    default: str | None
    available: list[str]
    models: dict[str, str]


def _resolve_llm(request: Request, requested: str | None) -> LLMClient:
    registry: dict[str, LLMClient] = getattr(request.app.state, "llm_registry", {}) or {}
    default: str | None = getattr(request.app.state, "default_backend", None)

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM backend not configured — set IRMA_LLM_BACKEND and creds",
        )

    if requested is None:
        # Same fallback as GET /chat/backends — never silently dispatch to a
        # hidden backend just because it's the configured default.
        if default in _HIDDEN_BACKENDS or default not in registry:
            visible = [name for name in registry if name not in _HIDDEN_BACKENDS]
            default = visible[0] if visible else None
        key = default
    else:
        key = requested

    if key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no default LLM backend available",
        )
    if key not in registry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown backend: {key!r} (available: {sorted(registry)})",
        )
    return registry[key]


async def _run_tool_calls(
    registry: ToolRegistry, calls: list[ToolCall]
) -> list[ToolResult]:
    """Invoke each call; ToolError outputs ride along as the tool's reply text."""
    results: list[ToolResult] = []
    for call in calls:
        try:
            content = await registry.call(call.name, call.args)
        except ToolError as exc:
            logger.warning(
                "chat.tool_error",
                tool=call.name,
                code=exc.code,
                detail=exc.detail,
            )
            content = f"error: {exc.code}" + (
                f" — {exc.detail}" if exc.detail else ""
            )
        results.append(ToolResult(tool_use_id=call.id, content=content))
    return results


@router.get("/chat/backends", response_model=BackendInfo)
async def get_backends(request: Request) -> BackendInfo:
    registry: dict[str, LLMClient] = getattr(request.app.state, "llm_registry", {}) or {}
    default: str | None = getattr(request.app.state, "default_backend", None)

    visible = {name: client for name, client in registry.items() if name not in _HIDDEN_BACKENDS}
    if default in _HIDDEN_BACKENDS or default not in visible:
        default = next(iter(visible), None)

    return BackendInfo(
        default=default,
        available=sorted(visible.keys()),
        models={name: client.model for name, client in visible.items()},
    )


@router.post("/chat", response_model=ChatResponse)
async def post_chat(request: Request, body: ChatRequest) -> ChatResponse:
    llm = _resolve_llm(request, body.backend)

    if llm.backend in _STATEFUL_BACKENDS:
        if not body.session_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"backend {llm.backend!r} requires session_id",
            )
        try:
            uuid.UUID(body.session_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"session_id must be a UUID: {body.session_id!r}",
            ) from exc

    bus: StateBus = request.app.state.bus
    tools: ToolRegistry | None = getattr(request.app.state, "tools", None)
    skip_tools = llm.backend in _STATEFUL_BACKENDS

    turns: list[ChatTurn] = [
        ChatTurn(role=m.role, content=m.content) for m in body.messages
    ]

    await bus.publish(AgentState.THINKING)
    reply: str | None = None
    try:
        if skip_tools:
            outcome = await llm.complete(
                system=_build_system_prompt([]),
                messages=turns,
                max_tokens=800,
                session_id=body.session_id,
            )
            assert isinstance(outcome, TextResult), (
                f"{llm.backend} returned non-text outcome with tools disabled"
            )
            reply = outcome.text
        else:
            for _iteration in range(MAX_TOOL_ITERATIONS):
                tool_specs = tools.specs() if tools is not None else []
                outcome = await llm.complete(
                    system=_build_system_prompt(tools.names() if tools is not None else []),
                    messages=turns,
                    tools=tool_specs or None,
                    max_tokens=800,
                )
                if isinstance(outcome, TextResult):
                    reply = outcome.text
                    break
                assert isinstance(outcome, ToolCallResult)
                if tools is None:
                    logger.error("chat.tool_call_without_registry")
                    reply = _STUCK_REPLY
                    break
                turns.append(
                    ChatTurn(
                        role="assistant",
                        content=outcome.preface,
                        tool_calls=outcome.calls,
                    )
                )
                results = await _run_tool_calls(tools, outcome.calls)
                turns.append(
                    ChatTurn(role="user", content="", tool_results=results)
                )
            if reply is None:
                logger.error(
                    "chat.tool_loop_exceeded", iterations=MAX_TOOL_ITERATIONS
                )
                reply = _STUCK_REPLY
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat.failed", backend=llm.backend)
        await bus.publish(AgentState.ALERT)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"chat backend failed: {exc}",
        ) from exc

    await bus.publish(AgentState.IDLE)
    return ChatResponse(reply=reply, backend=llm.backend, model=llm.model)
