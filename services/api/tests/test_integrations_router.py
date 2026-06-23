"""Integrations status endpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.config import Settings
from irma_api.models.profile import Profile
from irma_api.routers.integrations import router as integrations_router
from irma_api.runtime.profile_cache import ProfileCache


def _build_app(
    settings: Settings,
    llm: Any = None,
    profile_cache: ProfileCache | None = None,
) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.llm = llm
    if profile_cache is not None:
        app.state.profile_cache = profile_cache
    app.include_router(integrations_router, prefix="/api/v1")
    return app


def _fake_cache(
    owner_email: str | None = None,
    setup_complete: bool = False,
) -> ProfileCache:
    """Return a ProfileCache pre-loaded with a Profile instance (no DB needed)."""
    cache = ProfileCache.__new__(ProfileCache)
    cache._profile = Profile(
        owner_email=owner_email,
        setup_complete=setup_complete,
        updated_at=datetime.now(UTC),
    )
    return cache


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


# ---------------------------------------------------------------------------
# setup_complete + owner_email sourced from profile cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_setup_complete_defaults_false() -> None:
    """Without a profile cache, setup_complete must default to False."""
    app = _build_app(_settings())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["setup_complete"] is False


@pytest.mark.asyncio
async def test_status_setup_complete_from_profile_cache() -> None:
    """setup_complete=True in the profile cache must be reflected in the response."""
    cache = _fake_cache(setup_complete=True)
    app = _build_app(_settings(), profile_cache=cache)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["setup_complete"] is True


@pytest.mark.asyncio
async def test_status_user_email_sourced_from_profile_cache() -> None:
    """owner_email in the profile cache takes precedence over settings.irma_user_email."""
    cache = _fake_cache(owner_email="profile@example.com")
    app = _build_app(
        _settings(irma_user_email="settings@example.com"),
        profile_cache=cache,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["user_email"] == "profile@example.com"


@pytest.mark.asyncio
async def test_status_user_email_falls_back_to_settings() -> None:
    """When profile.owner_email is None, settings.irma_user_email is used."""
    cache = _fake_cache(owner_email=None)
    app = _build_app(
        _settings(irma_user_email="settings@example.com"),
        profile_cache=cache,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        body = (await c.get("/api/v1/integrations/google/status")).json()
    assert body["user_email"] == "settings@example.com"
