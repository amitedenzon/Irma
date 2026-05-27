"""LLM client abstraction.

Both LeadAgent (JSON-only standup synthesis) and the /chat endpoint
(free-form persona reply) need a single async ``complete()`` call. We hide
provider differences behind :class:`LLMClient` so the rest of the codebase
never sees an SDK type and the backend is selectable via env.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, cast, runtime_checkable

import httpx
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from irma_api.config import Settings

logger = structlog.get_logger(__name__)


Role = Literal["user", "assistant"]


class ChatTurn(BaseModel):
    """One turn in a conversation. System prompt is passed separately."""

    role: Role
    content: str


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic async chat completion surface."""

    backend: str
    model: str

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        max_tokens: int = 1500,
    ) -> str: ...


class AnthropicLLM:
    backend = "anthropic"

    def __init__(self, *, client: AsyncAnthropic, model: str) -> None:
        self._client = client
        self.model = model

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        max_tokens: int = 1500,
    ) -> str:
        wire: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in messages]
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=cast(Any, wire),
        )
        parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                parts.append(str(getattr(block, "text", "")))
        return "\n".join(parts).strip()


class OllamaLLM:
    """Ollama via its native /api/chat endpoint.

    We use a long-lived httpx client and a generous read timeout — a cold
    7B model on an M2 Air can take 20+ seconds for the first token.
    """

    backend = "ollama"

    def __init__(self, *, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        max_tokens: int = 1500,
    ) -> str:
        wire: list[dict[str, str]] = [{"role": "system", "content": system}]
        wire.extend({"role": m.role, "content": m.content} for m in messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        resp = await self._http.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        # Ollama shape: {"message": {"role": "assistant", "content": "..."}, ...}
        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"unexpected ollama response shape: {data!r}")
        return content.strip()


def build_llm_client(settings: Settings) -> LLMClient | None:
    """Construct the configured backend, or ``None`` if it can't be built.

    Returning None (instead of raising) lets the app boot in degraded mode —
    the standup + chat endpoints will 503, but observers still collect.
    """
    backend = settings.irma_llm_backend
    if backend == "anthropic":
        if settings.anthropic_api_key is None:
            logger.warning("llm.anthropic_unconfigured")
            return None
        client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        return AnthropicLLM(client=client, model=settings.anthropic_model)
    if backend == "ollama":
        return OllamaLLM(base_url=settings.ollama_base_url, model=settings.ollama_model)
    raise ValueError(f"unknown IRMA_LLM_BACKEND: {backend!r}")
