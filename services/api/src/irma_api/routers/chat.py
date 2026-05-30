"""Free-form chat with Irma — runs the tool-call loop on LLM outputs."""

from __future__ import annotations

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
    image_b64: str | None = None   # base64-encoded image for vision models


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None       # override the default model for this request


class ChatResponse(BaseModel):
    reply: str
    backend: str
    model: str


def _resolve_llm(request: Request, model_override: str | None = None) -> LLMClient:
    from irma_api.agents.llm import OllamaLLM

    registry: dict[str, LLMClient] = getattr(request.app.state, "llm_registry", {}) or {}
    default: str | None = getattr(request.app.state, "default_backend", None)

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM backend not configured — set IRMA_LLM_BACKEND and creds",
        )
    if default is None or default not in registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no default LLM backend available",
        )
    llm = registry[default]

    # If a model override was requested and the backend is Ollama, swap the model.
    if model_override and hasattr(llm, "model") and llm.backend == "ollama":
        settings = request.app.state.settings
        llm = OllamaLLM(settings=settings, model_override=model_override)

    return llm


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


@router.post("/chat", response_model=ChatResponse)
async def post_chat(request: Request, body: ChatRequest) -> ChatResponse:
    llm = _resolve_llm(request, body.model)

    bus: StateBus = request.app.state.bus
    tools: ToolRegistry | None = getattr(request.app.state, "tools", None)

    turns: list[ChatTurn] = [
        ChatTurn(role=m.role, content=m.content, image_b64=m.image_b64)
        for m in body.messages
    ]

    await bus.publish(AgentState.THINKING)
    reply: str | None = None
    try:
        for _iteration in range(MAX_TOOL_ITERATIONS):
            tool_specs = tools.specs() if tools is not None else []
            outcome = await llm.complete(
                system=_build_system_prompt(tools.names() if tools else []),
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
            logger.error("chat.tool_loop_exceeded", iterations=MAX_TOOL_ITERATIONS)
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
