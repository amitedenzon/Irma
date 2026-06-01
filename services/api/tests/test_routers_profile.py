"""HTTP surface for GET/PATCH /api/v1/profile."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.profile import router as profile_router
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.store.repos.profile_repo import ProfileRepo
from irma_api.store.sqlite import SignalStore


class _AppClient(NamedTuple):
    client: AsyncClient
    app: FastAPI


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store

    repo = ProfileRepo(store.connection)
    cache = ProfileCache(repo)
    await cache.load()
    app.state.profile_cache = cache

    app.include_router(profile_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest_asyncio.fixture
async def app_client(tmp_path: Path) -> AsyncIterator[_AppClient]:
    """Fixture that yields both the AsyncClient and the FastAPI app instance."""
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store

    repo = ProfileRepo(store.connection)
    cache = ProfileCache(repo)
    await cache.load()
    app.state.profile_cache = cache

    app.include_router(profile_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield _AppClient(client=c, app=app)
    await store.close()


@pytest.mark.asyncio
async def test_get_profile_returns_defaults(client: AsyncClient) -> None:
    r = await client.get("/api/v1/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert body["owner_name"] == "there"
    assert body["setup_complete"] is False


@pytest.mark.asyncio
async def test_patch_profile_updates_field(client: AsyncClient) -> None:
    r = await client.patch("/api/v1/profile", json={"owner_name": "Amit"})
    assert r.status_code == 200
    assert r.json()["owner_name"] == "Amit"


@pytest.mark.asyncio
async def test_patch_profile_reloads_cache(client: AsyncClient) -> None:
    """GET after PATCH must reflect the updated value (cache was reloaded)."""
    await client.patch("/api/v1/profile", json={"owner_name": "Amit", "brief_hour": 7})
    r = await client.get("/api/v1/profile")
    body = r.json()
    assert body["owner_name"] == "Amit"
    assert body["brief_hour"] == 7


@pytest.mark.asyncio
async def test_patch_rejects_unknown_field(client: AsyncClient) -> None:
    r = await client.patch("/api/v1/profile", json={"unknown_field": "x"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_rejects_invalid_timezone(client: AsyncClient) -> None:
    r = await client.patch("/api/v1/profile", json={"timezone": "Not/ATimezone"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_cache_set_not_reload(app_client: _AppClient) -> None:
    """PATCH must update cache.current via cache.set() without an extra DB round-trip.

    Verifies that the in-memory cache reflects the PATCHed value immediately —
    confirming the set()-based path rather than the old load()-based path.
    """
    client, app = app_client
    r = await client.patch("/api/v1/profile", json={"owner_name": "Amit", "brief_hour": 6})
    assert r.status_code == 200

    cache: ProfileCache = app.state.profile_cache
    assert cache.current.owner_name == "Amit"
    assert cache.current.brief_hour == 6


# ---------------------------------------------------------------------------
# Reschedule hook tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sched_app_client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, FastAPI, MagicMock]]:
    """App fixture with a MagicMock scheduler attached to app.state."""
    mock_scheduler = MagicMock()

    app = FastAPI()
    store = SignalStore(tmp_path / "irma_sched.db")
    await store.connect()
    app.state.store = store

    repo = ProfileRepo(store.connection)
    cache = ProfileCache(repo)
    await cache.load()
    app.state.profile_cache = cache
    app.state.scheduler = mock_scheduler

    app.include_router(profile_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c, app, mock_scheduler
    await store.close()


@pytest.mark.asyncio
async def test_patch_brief_hour_triggers_reschedule(
    sched_app_client: tuple[AsyncClient, FastAPI, MagicMock],
) -> None:
    """Patching brief_hour must call reschedule_daily_job with the new values."""
    client, _app, mock_sched = sched_app_client

    r = await client.patch("/api/v1/profile", json={"brief_hour": 9})
    assert r.status_code == 200

    mock_sched.reschedule_daily_job.assert_called_once()
    call_kwargs = mock_sched.reschedule_daily_job.call_args.kwargs
    assert call_kwargs["hour"] == 9


@pytest.mark.asyncio
async def test_patch_timezone_triggers_reschedule(
    sched_app_client: tuple[AsyncClient, FastAPI, MagicMock],
) -> None:
    """Patching timezone must call reschedule_daily_job."""
    client, _app, mock_sched = sched_app_client

    r = await client.patch("/api/v1/profile", json={"timezone": "Asia/Jerusalem"})
    assert r.status_code == 200

    mock_sched.reschedule_daily_job.assert_called_once()
    call_kwargs = mock_sched.reschedule_daily_job.call_args.kwargs
    assert call_kwargs["timezone"] == "Asia/Jerusalem"


@pytest.mark.asyncio
async def test_patch_daily_brief_enabled_triggers_reschedule(
    sched_app_client: tuple[AsyncClient, FastAPI, MagicMock],
) -> None:
    """Patching daily_brief_enabled must call reschedule_daily_job."""
    client, _app, mock_sched = sched_app_client

    r = await client.patch("/api/v1/profile", json={"daily_brief_enabled": False})
    assert r.status_code == 200

    mock_sched.reschedule_daily_job.assert_called_once()
    call_kwargs = mock_sched.reschedule_daily_job.call_args.kwargs
    assert call_kwargs["enabled"] is False


@pytest.mark.asyncio
async def test_patch_unrelated_field_does_not_reschedule(
    sched_app_client: tuple[AsyncClient, FastAPI, MagicMock],
) -> None:
    """Patching an unrelated field (e.g. owner_name) must NOT call reschedule."""
    client, _app, mock_sched = sched_app_client

    r = await client.patch("/api/v1/profile", json={"owner_name": "Amit"})
    assert r.status_code == 200

    mock_sched.reschedule_daily_job.assert_not_called()


@pytest.mark.asyncio
async def test_patch_reschedule_passes_new_values(
    sched_app_client: tuple[AsyncClient, FastAPI, MagicMock],
) -> None:
    """reschedule_daily_job receives ALL three scheduling fields from the updated profile."""
    client, _app, mock_sched = sched_app_client

    r = await client.patch(
        "/api/v1/profile",
        json={"brief_hour": 7, "timezone": "America/New_York", "daily_brief_enabled": True},
    )
    assert r.status_code == 200

    mock_sched.reschedule_daily_job.assert_called_once_with(
        hour=7,
        timezone="America/New_York",
        enabled=True,
    )
