"""Smoke: create_app() registers integrations + tools registry, lifespan runs cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from irma_api.app import create_app
from irma_api.config import get_settings


def test_app_boots_and_serves_integrations_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # chdir away from the project .env so Settings only sees the env we set here.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app) as client:                # context manager triggers lifespan
        resp = client.get("/api/v1/integrations/google/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["calendar_linked"] is False
        assert body["resend_linked"] is False
        # ToolRegistry must always exist on app.state.
        assert hasattr(app.state, "tools")
        # Empty registry when RESEND_API_KEY + IRMA_USER_EMAIL aren't both set.
        assert app.state.tools.names() == []


def test_app_registers_send_email_when_resend_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot2.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("IRMA_USER_EMAIL", "amit@example.com")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        assert "send_email" in app.state.tools.names()
