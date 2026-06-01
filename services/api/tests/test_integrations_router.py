"""Integrations status endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.config import Settings
from irma_api.routers.integrations import router as integrations_router


def _build_app(settings: Settings, llm: Any = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.llm = llm
    app.include_router(integrations_router, prefix="/api/v1")
    return app


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


class _FakeLLM:
    backend = "anthropic"
    model = "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_status_unlinked_when_nothing_configured() -> None:
    app = _build_app(_settings(), llm=_FakeLLM())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/integrations/google/status")
    body = resp.json()
    assert resp.status_code == 200
    assert body["calendar_linked"] is False
    assert body["resend_linked"] is False
    assert body["user_email"] is None
    assert body["llm_backend"] == "anthropic"
    assert body["llm_model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_status_includes_reminders_fields() -> None:
    app = _build_app(_settings(), llm=_FakeLLM())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/integrations/google/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "reminders_linked" in data
    assert data["reminders_linked"] is False
    assert "reminders_last_sync_at" in data
    assert data["reminders_last_sync_at"] is None
    assert "reminders_last_sync_error" in data


@pytest.mark.asyncio
async def test_calendar_linked_when_refresh_token_set() -> None:
    app = _build_app(
        _settings(
            google_oauth_client_id="cid",
            google_oauth_client_secret="sec",
            google_oauth_refresh_token="rt",
            irma_user_email="amit@example.com",
        ),
        llm=_FakeLLM(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/integrations/google/status")
    body = resp.json()
    assert body["calendar_linked"] is True
    # resend_linked stays false until RESEND_API_KEY is also set.
    assert body["resend_linked"] is False
    assert body["user_email"] == "amit@example.com"


@pytest.mark.asyncio
async def test_resend_linked_requires_key_and_user_email() -> None:
    """Both RESEND_API_KEY and IRMA_USER_EMAIL must be present."""
    only_key = _build_app(
        _settings(resend_api_key="re_xxx"),
        llm=_FakeLLM(),
    )
    transport = ASGITransport(app=only_key)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["resend_linked"] is False

    only_email = _build_app(
        _settings(irma_user_email="amit@example.com"),
        llm=_FakeLLM(),
    )
    transport = ASGITransport(app=only_email)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["resend_linked"] is False

    both = _build_app(
        _settings(
            resend_api_key="re_xxx",
            irma_user_email="amit@example.com",
        ),
        llm=_FakeLLM(),
    )
    transport = ASGITransport(app=both)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["resend_linked"] is True


@pytest.mark.asyncio
async def test_status_when_llm_missing() -> None:
    app = _build_app(_settings(), llm=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/integrations/google/status")
    body = resp.json()
    assert body["llm_backend"] is None
    assert body["llm_model"] is None
