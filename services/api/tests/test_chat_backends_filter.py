"""`/chat/backends` filter mechanism and `_resolve_llm` fallback.

The hidden-backend set is empty by default — `claude_cli` ships its own MCP
tools (Gmail, Calendar) so there's no reason to hide it. These tests:

1. Confirm the empty default lets every registered backend through.
2. Confirm the filter machinery still works when something IS hidden, via
   `monkeypatch.setattr` — so the knob is exercised even though no name is
   currently hidden in production.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from irma_api.agents.llm import ChatTurn, TextResult
from irma_api.app import create_app
from irma_api.config import get_settings
from irma_api.routers import chat as chat_router
from irma_api.tools.base import ToolSpec


class _StubLLM:
    backend = "stub"
    model = "stub-1"

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
        session_id: str | None = None,
    ) -> TextResult:
        del system, messages, tools, max_tokens, session_id
        return TextResult(text="ok")


class _OllamaStubLLM(_StubLLM):
    backend = "ollama"


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "filter.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()
    return create_app()


def test_default_hidden_set_is_empty() -> None:
    """claude_cli ships its own MCP tools, so nothing is hidden by default."""
    assert not chat_router._HIDDEN_BACKENDS
    assert isinstance(chat_router._HIDDEN_BACKENDS, frozenset)


def test_backends_endpoint_lists_every_registered_backend_when_nothing_hidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {
            "ollama": _StubLLM(),
            "anthropic": _StubLLM(),
            "claude_cli": _StubLLM(),
        }
        app.state.default_backend = "claude_cli"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["available"]) == {"ollama", "anthropic", "claude_cli"}
        assert body["default"] == "claude_cli"


def test_backends_endpoint_filters_when_a_backend_is_hidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """If a future config opts to hide a backend, the filter mechanism works."""
    monkeypatch.setattr(chat_router, "_HIDDEN_BACKENDS", frozenset({"anthropic"}))
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {
            "ollama": _StubLLM(),
            "anthropic": _StubLLM(),
        }
        app.state.default_backend = "anthropic"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert "anthropic" not in body["available"]
        assert "anthropic" not in body["models"]
        assert body["default"] == "ollama"


def test_backends_endpoint_returns_null_default_when_only_hidden_backends_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(chat_router, "_HIDDEN_BACKENDS", frozenset({"anthropic"}))
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {"anthropic": _StubLLM()}
        app.state.default_backend = "anthropic"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] == []
        assert body["default"] is None


def test_post_chat_with_no_backend_falls_back_when_default_is_hidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """`_resolve_llm` mirrors `get_backends`: a hidden default is bypassed
    when no explicit `backend` is provided."""
    monkeypatch.setattr(chat_router, "_HIDDEN_BACKENDS", frozenset({"anthropic"}))
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {
            "ollama": _OllamaStubLLM(),
            "anthropic": _StubLLM(),
        }
        app.state.default_backend = "anthropic"

        resp = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["backend"] == "ollama"


def test_post_chat_with_explicit_claude_cli_still_400s_without_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """`claude_cli` is stateful regardless of hidden status — `session_id` is
    still required when it's the explicit target."""

    class _CliStubLLM(_StubLLM):
        backend = "claude_cli"

    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {
            "ollama": _StubLLM(),
            "claude_cli": _CliStubLLM(),
        }
        app.state.default_backend = "ollama"

        resp = client.post(
            "/api/v1/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "backend": "claude_cli",
            },
        )
        assert resp.status_code == 400
        assert "session_id" in resp.text
