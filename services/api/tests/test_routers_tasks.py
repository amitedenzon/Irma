"""HTTP surface for /api/v1/tasks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.projects import router as projects_router
from irma_api.routers.tasks import router as tasks_router
from irma_api.store.sqlite import SignalStore


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


async def _mk_project(client: AsyncClient, name: str = "P") -> str:
    r = await client.post("/api/v1/projects", json={"name": name})
    return r.json()["id"]


@pytest.mark.asyncio
async def test_create_and_get(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    r = await client.post(
        "/api/v1/tasks",
        json={"project_id": pid, "title": "Draft", "due_date": "2026-05-28"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Draft"
    assert body["status"] == "todo"
    rg = await client.get(f"/api/v1/tasks/{body['id']}")
    assert rg.status_code == 200
    assert rg.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_create_with_missing_project_404(client: AsyncClient) -> None:
    r = await client.post("/api/v1/tasks", json={"project_id": "nope", "title": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_status_done_sets_completed_at(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    t = (await client.post("/api/v1/tasks", json={"project_id": pid, "title": "x"})).json()
    r = await client.patch(f"/api/v1/tasks/{t['id']}", json={"status": "done"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_complete_shortcut_is_idempotent(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    t = (await client.post("/api/v1/tasks", json={"project_id": pid, "title": "x"})).json()
    r1 = await client.post(f"/api/v1/tasks/{t['id']}/complete")
    r2 = await client.post(f"/api/v1/tasks/{t['id']}/complete")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["completed_at"] == r2.json()["completed_at"]


@pytest.mark.asyncio
async def test_list_filters(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    await client.post(
        "/api/v1/tasks",
        json={"project_id": pid, "title": "today", "scheduled_for": "2026-05-27"},
    )
    await client.post(
        "/api/v1/tasks",
        json={"project_id": pid, "title": "next", "scheduled_for": "2026-06-03"},
    )
    r = await client.get(
        f"/api/v1/tasks?project_id={pid}"
        "&scheduled_from=2026-05-27&scheduled_to=2026-05-27"
    )
    assert [t["title"] for t in r.json()] == ["today"]


@pytest.mark.asyncio
async def test_delete(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    t = (await client.post("/api/v1/tasks", json={"project_id": pid, "title": "x"})).json()
    r = await client.delete(f"/api/v1/tasks/{t['id']}")
    assert r.status_code == 204
    r2 = await client.get(f"/api/v1/tasks/{t['id']}")
    assert r2.status_code == 404
