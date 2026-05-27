"""Free-form chat with Irma — small surface for testing the active LLM backend."""

from __future__ import annotations

from typing import Final

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from irma_api.agents.llm import ChatTurn, LLMClient, Role
from irma_api.runtime.state import AgentState, StateBus

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["chat"])


_SYSTEM_PROMPT: Final[str] = """\
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


class ChatMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    backend: str
    model: str


@router.post("/chat", response_model=ChatResponse)
async def post_chat(request: Request, body: ChatRequest) -> ChatResponse:
    llm: LLMClient | None = getattr(request.app.state, "llm", None)
    if llm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM backend not configured — set IRMA_LLM_BACKEND and creds",
        )

    bus: StateBus = request.app.state.bus
    await bus.publish(AgentState.THINKING)
    try:
        turns = [ChatTurn(role=m.role, content=m.content) for m in body.messages]
        reply = await llm.complete(system=_SYSTEM_PROMPT, messages=turns, max_tokens=800)
    except Exception as exc:
        logger.exception("chat.failed", backend=llm.backend)
        await bus.publish(AgentState.ALERT)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"chat backend failed: {exc}",
        ) from exc
    await bus.publish(AgentState.IDLE)
    return ChatResponse(reply=reply, backend=llm.backend, model=llm.model)
