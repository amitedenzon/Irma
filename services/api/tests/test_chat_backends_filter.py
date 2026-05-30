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
