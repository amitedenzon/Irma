"""HTTP surface for GET/PATCH /api/v1/profile."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.profile import router as profile_router
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.store.repos.profile_repo import ProfileRepo
from irma_api.store.sqlite import SignalStore


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
