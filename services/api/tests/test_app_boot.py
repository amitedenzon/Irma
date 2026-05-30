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
        # Project + task tools are always present; optional tools absent when
        # RESEND_API_KEY + IRMA_USER_EMAIL + GOOGLE_OAUTH_REFRESH_TOKEN aren't set.
        names = set(app.state.tools.names())
        assert {"list_projects", "create_project", "list_tasks", "create_task", "complete_task"}.issubset(names)
        assert "send_email" not in names
        assert "read_calendar" not in names
        assert "create_calendar_event" not in names


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


def test_app_registers_project_and_task_tools_unconditionally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project + task tools need only the store, which is always present."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot3.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        names = set(app.state.tools.names())
        assert {"list_projects", "create_project"}.issubset(names)
        assert {"list_tasks", "create_task", "complete_task"}.issubset(names)


def test_app_registers_create_calendar_event_when_oauth_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot4.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "rt")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        names = set(app.state.tools.names())
        assert "read_calendar" in names
        assert "create_calendar_event" in names


def test_app_does_not_register_calendar_tools_with_partial_oauth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh token alone is not enough — client id/secret are also required."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot5.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "rt")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        names = set(app.state.tools.names())
        assert "read_calendar" not in names
        assert "create_calendar_event" not in names


def test_app_does_not_register_anthropic_with_blank_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defined-but-blank ANTHROPIC_API_KEY must be treated as unset."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot_blank_anthropic.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "ollama")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # defined but blank
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        assert "anthropic" not in app.state.llm_registry


def test_app_does_not_register_send_email_with_blank_resend_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defined-but-blank RESEND_API_KEY must be treated as unset."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot_blank_resend.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "ollama")
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("IRMA_USER_EMAIL", "amit@example.com")
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        assert "send_email" not in app.state.tools.names()
