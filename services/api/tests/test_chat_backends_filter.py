"""GET /chat/backends must not expose claude_cli (no tool support)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from irma_api.app import create_app
from irma_api.agents.llm import ChatTurn, TextResult
from irma_api.config import get_settings
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


def test_backends_endpoint_hides_claude_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        # Inject a fake registry containing claude_cli to prove the filter works
        # even when the CLI is installed on the host.
        app.state.llm_registry = {
            "ollama": _StubLLM(),
            "anthropic": _StubLLM(),
            "claude_cli": _StubLLM(),
        }
        app.state.default_backend = "claude_cli"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert "claude_cli" not in body["available"]
        assert "claude_cli" not in body["models"]
        # Default falls back to a visible backend.
        assert body["default"] in body["available"]


def test_backends_endpoint_returns_null_default_when_only_hidden_backends_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {"claude_cli": _StubLLM()}
        app.state.default_backend = "claude_cli"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] == []
        assert body["default"] is None


def test_hidden_and_stateful_backend_sets_stay_aligned() -> None:
    """Canary: every hidden backend is also stateful (can't host tools), and
    every stateful backend is hidden from the UI. If you change one set you
    must change the other — they encode the same constraint from two angles."""
    from irma_api.routers.chat import _HIDDEN_BACKENDS, _STATEFUL_BACKENDS

    assert _HIDDEN_BACKENDS == _STATEFUL_BACKENDS


def test_post_chat_with_no_backend_falls_back_when_default_is_hidden(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """POST /chat with no `backend` field must not silently use claude_cli
    just because it's the configured default. The fallback mirrors the rule
    in GET /chat/backends."""
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        visible_stub = _StubLLM()
        hidden_stub = _StubLLM()
        app.state.llm_registry = {
            "ollama": visible_stub,
            "claude_cli": hidden_stub,
        }
        app.state.default_backend = "claude_cli"

        resp = client.post(
            "/api/v1/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200


def test_post_chat_with_explicit_claude_cli_still_400s_without_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Explicit opt-in to a hidden backend is still honored (back-compat for
    scripts/tests)."""

    class _CliStubLLM(_StubLLM):
        backend = "claude_cli"

    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {
            "ollama": _StubLLM(),
            "claude_cli": _CliStubLLM(),
        }
        app.state.default_backend = "ollama"

        # The claude_cli backend requires session_id — passing the backend
        # explicitly but no session_id should produce a 400, confirming the
        # request reached the claude_cli path (not the ollama fallback).
        resp = client.post(
            "/api/v1/chat",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "backend": "claude_cli",
            },
        )
        assert resp.status_code == 400
        assert "session_id" in resp.text
