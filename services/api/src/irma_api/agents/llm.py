"""LLM client abstraction.

Both LeadAgent (JSON-only standup synthesis) and the /chat endpoint (free-form
persona reply, possibly with tool use) need a single async ``complete()`` call.
We hide provider differences behind :class:`LLMClient` so the rest of the
codebase never sees an SDK type and the backend is selectable via env.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal, Protocol, cast, runtime_checkable

import httpx
import structlog
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from irma_api.config import Settings
from irma_api.tools.base import ToolSpec

logger = structlog.get_logger(__name__)


Role = Literal["user", "assistant"]


class ToolCall(BaseModel):
    """One tool the model wants to invoke."""

    id: str
    name: str
    args: dict[str, Any]


class ToolResult(BaseModel):
    """The output of a tool invocation, ready to feed back to the model."""

    tool_use_id: str
    content: str


class ChatTurn(BaseModel):
    """One turn in a conversation. System prompt is passed separately.

    Tool-use extensions are optional and additive:
    * ``tool_calls`` is set on an assistant turn that asked to call tools.
    * ``tool_results`` is set on a user turn that is replying with results.
    """

    role: Role
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)


class TextResult(BaseModel):
    text: str


class ToolCallResult(BaseModel):
    calls: list[ToolCall]
    preface: str = ""  # text the assistant emitted before the tool call(s)


CompleteResult = TextResult | ToolCallResult


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic async chat completion surface.

    ``session_id`` is honored only by backends that persist conversation
    state on disk (currently :class:`ClaudeCliLLM`); other backends accept
    and ignore it.
    """

    backend: str
    model: str

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
        session_id: str | None = None,
    ) -> CompleteResult: ...


def _anthropic_messages(turns: list[ChatTurn]) -> list[dict[str, Any]]:
    """Translate ChatTurn list into Anthropic Messages wire format."""
    out: list[dict[str, Any]] = []
    for t in turns:
        if t.tool_calls:
            content: list[dict[str, Any]] = []
            if t.content:
                content.append({"type": "text", "text": t.content})
            content.extend(
                {
                    "type": "tool_use",
                    "id": c.id,
                    "name": c.name,
                    "input": c.args,
                }
                for c in t.tool_calls
            )
            out.append({"role": t.role, "content": content})
        elif t.tool_results:
            out.append(
                {
                    "role": t.role,
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.tool_use_id,
                            "content": r.content,
                        }
                        for r in t.tool_results
                    ],
                }
            )
        else:
            out.append({"role": t.role, "content": t.content})
    return out


def _anthropic_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": s.name,
            "description": s.description,
            "input_schema": s.input_schema,
        }
        for s in specs
    ]


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
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
        session_id: str | None = None,
    ) -> CompleteResult:
        del session_id  # Anthropic keeps state client-side; nothing to thread through.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": _anthropic_messages(messages),
        }
        if tools:
            kwargs["tools"] = _anthropic_tools(tools)

        response = await self._client.messages.create(**cast(Any, kwargs))

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(str(getattr(block, "text", "")))
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=str(getattr(block, "id", "")),
                        name=str(getattr(block, "name", "")),
                        args=dict(getattr(block, "input", {}) or {}),
                    )
                )

        if tool_calls:
            return ToolCallResult(
                calls=tool_calls, preface="\n".join(text_parts).strip()
            )
        return TextResult(text="\n".join(text_parts).strip())


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
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
        session_id: str | None = None,
    ) -> CompleteResult:
        del session_id  # Ollama is stateless; we send full history each turn.
        wire: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            if m.tool_calls:
                wire.append(
                    {
                        "role": "assistant",
                        "content": m.content,
                        "tool_calls": [
                            {
                                "function": {
                                    "name": c.name,
                                    "arguments": c.args,
                                }
                            }
                            for c in m.tool_calls
                        ],
                    }
                )
            elif m.tool_results:
                for r in m.tool_results:
                    wire.append({"role": "tool", "content": r.content})
            else:
                wire.append({"role": m.role, "content": m.content})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": wire,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": s.name,
                        "description": s.description,
                        "parameters": s.input_schema,
                    },
                }
                for s in tools
            ]

        resp = await self._http.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message") or {}

        raw_calls = msg.get("tool_calls") or []
        if raw_calls:
            calls: list[ToolCall] = []
            for i, raw in enumerate(raw_calls):
                fn = raw.get("function") or {}
                calls.append(
                    ToolCall(
                        id=str(raw.get("id") or f"ollama_{i}"),
                        name=str(fn.get("name", "")),
                        args=dict(fn.get("arguments") or {}),
                    )
                )
            preface = str(msg.get("content") or "").strip()
            return ToolCallResult(calls=calls, preface=preface)

        content = msg.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"unexpected ollama response shape: {data!r}")
        return TextResult(text=content.strip())


class ClaudeAuthError(RuntimeError):
    """Raised when the `claude` CLI reports the session is unauthenticated."""


class ClaudeCliLLM:
    """Shell out to ``claude -p`` so chat rides the user's Claude subscription.

    Each turn invokes ``claude -p --session-id <uuid> ... "<last user message>"``.
    Conversation continuity is delegated to Claude's own session file on disk —
    addressed by the UUID the caller threads through every turn — so we only
    ship the latest user message as the prompt argument.

    Tool use is *not* supported in this v1: the chat router skips its tool
    loop entirely when this backend is active, and ``--disallowedTools "*"``
    keeps Claude from reaching for its built-in filesystem/bash tools.
    """

    backend = "claude_cli"

    def __init__(
        self,
        *,
        binary: str = "claude",
        model: str | None = None,
        cwd: Path | None = None,
        timeout_seconds: float = 90.0,
    ) -> None:
        self._binary = binary
        # We surface a stable string for /chat's response so the UI can show
        # something sensible before the first turn. After a real turn we
        # update from the JSON envelope's `modelUsage` key.
        self.model = model or "claude-default"
        self._configured_model = model
        self._cwd = str(cwd) if cwd is not None else None
        self._timeout = timeout_seconds

    def _argv(self, *, system: str, last_user_message: str, session_id: str) -> list[str]:
        argv: list[str] = [
            self._binary,
            "-p",
            "--session-id",
            session_id,
            "--system-prompt",
            system,
            "--disallowedTools",
            "*",
            "--disable-slash-commands",
            "--output-format",
            "json",
            "--permission-mode",
            "default",
        ]
        if self._configured_model is not None:
            argv.extend(["--model", self._configured_model])
        argv.append(last_user_message)
        return argv

    @staticmethod
    def _last_user_text(messages: list[ChatTurn]) -> str:
        for turn in reversed(messages):
            if turn.role == "user" and turn.content:
                return turn.content
        raise ValueError("claude_cli: no user message to send")

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
        session_id: str | None = None,
    ) -> CompleteResult:
        del max_tokens  # CLI has no equivalent flag.
        if tools:
            # The chat router is responsible for skipping the tool loop for
            # this backend; if a caller still passes tools, ignore them but
            # log once so the mistake surfaces in dev.
            logger.warning("claude_cli.tools_ignored", count=len(tools))
        if not session_id:
            raise ValueError("claude_cli backend requires a session_id")
        try:
            uuid.UUID(session_id)
        except ValueError as exc:
            raise ValueError(f"claude_cli session_id must be a UUID: {session_id!r}") from exc

        argv = self._argv(
            system=system,
            last_user_message=self._last_user_text(messages),
            session_id=session_id,
        )
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self._cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise TimeoutError(
                f"claude timed out after {self._timeout:.0f}s"
            ) from exc

        if proc.returncode != 0:
            tail = stderr_b.decode("utf-8", errors="replace")[-500:].strip()
            raise RuntimeError(f"claude exited {proc.returncode}: {tail}")

        try:
            envelope = json.loads(stdout_b.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            preview = stdout_b[:200].decode("utf-8", errors="replace")
            raise RuntimeError(f"claude returned non-JSON: {preview!r}") from exc

        if envelope.get("is_error"):
            subtype = str(envelope.get("subtype") or "error")
            detail = str(envelope.get("result") or envelope.get("message") or "").strip()
            if "auth" in subtype.lower() or "login" in detail.lower():
                raise ClaudeAuthError(
                    "claude not authenticated — run `claude /login` once"
                )
            raise RuntimeError(f"claude {subtype}: {detail}")

        # Update self.model from the envelope so /chat's response reflects
        # what was actually used (`claude-opus-4-7[1m]` etc.).
        model_usage = envelope.get("modelUsage") or {}
        if isinstance(model_usage, dict) and model_usage:
            self.model = next(iter(model_usage))

        result = envelope.get("result")
        if not isinstance(result, str):
            raise RuntimeError(f"claude envelope missing 'result': {envelope!r}")
        return TextResult(text=result.strip())


def build_llm_registry(settings: Settings) -> tuple[dict[str, LLMClient], str | None]:
    """Build every backend that can stand up on current config.

    Returns ``(registry, default_backend)``. ``default_backend`` is the key
    matching ``settings.irma_llm_backend`` if it landed in the registry,
    otherwise the first registered key, otherwise ``None``.

    Returning a possibly-empty registry (instead of raising) lets the app
    boot in degraded mode — the standup + chat endpoints will 503 / 400,
    but observers still collect.
    """
    registry: dict[str, LLMClient] = {}

    if settings.anthropic_api_key is not None:
        client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
        registry["anthropic"] = AnthropicLLM(client=client, model=settings.anthropic_model)
    else:
        logger.info("llm.anthropic_unconfigured")

    registry["ollama"] = OllamaLLM(
        base_url=settings.ollama_base_url, model=settings.ollama_model
    )

    if shutil.which(settings.claude_cli_binary) is not None:
        registry["claude_cli"] = ClaudeCliLLM(
            binary=settings.claude_cli_binary,
            model=settings.claude_cli_model,
            timeout_seconds=settings.claude_cli_timeout_seconds,
        )
    else:
        logger.info("llm.claude_cli_unavailable", binary=settings.claude_cli_binary)

    desired = settings.irma_llm_backend
    default: str | None
    if desired in registry:
        default = desired
    elif registry:
        default = next(iter(registry))
        logger.warning(
            "llm.default_fallback", desired=desired, chosen=default
        )
    else:
        default = None

    return registry, default


def build_llm_client(settings: Settings) -> LLMClient | None:
    """Back-compat shim: return the default LLM from the registry.

    New code should call :func:`build_llm_registry` and dispatch by name.
    """
    registry, default = build_llm_registry(settings)
    return registry.get(default) if default else None
