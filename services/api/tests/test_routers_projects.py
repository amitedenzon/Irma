"""HTTP surface for /api/v1/projects."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.projects import router as projects_router
from irma_api.store.sqlite import SignalStore


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store
    app.include_router(projects_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
async def test_create_and_list(client: AsyncClient) -> None:
    r = await client.post("/api/v1/projects", json={"name": "Thesis"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Thesis"
    assert body["status"] == "active"

    r = await client.get("/api/v1/projects")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["Thesis"]


@pytest.mark.asyncio
async def test_create_duplicate_name_409(client: AsyncClient) -> None:
    await client.post("/api/v1/projects", json={"name": "X"})
    r = await client.post("/api/v1/projects", json={"name": "x"})
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


@pytest.mark.asyncio
async def test_get_404(client: AsyncClient) -> None:
    r = await client.get("/api/v1/projects/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_patch(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/projects", json={"name": "X"})).json()
    r = await client.patch(
        f"/api/v1/projects/{created['id']}", json={"priority": 1}
    )
    assert r.status_code == 200
    assert r.json()["priority"] == 1


@pytest.mark.asyncio
async def test_delete(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/projects", json={"name": "X"})).json()
    r = await client.delete(f"/api/v1/projects/{created['id']}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_list_filters_by_status(client: AsyncClient) -> None:
    a = (await client.post("/api/v1/projects", json={"name": "A"})).json()
    await client.post("/api/v1/projects", json={"name": "B"})
    await client.patch(
        f"/api/v1/projects/{a['id']}", json={"status": "archived"}
    )

    active = await client.get("/api/v1/projects?status=active")
    assert [p["name"] for p in active.json()] == ["B"]

    archived = await client.get("/api/v1/projects?status=archived")
    assert [p["name"] for p in archived.json()] == ["A"]
