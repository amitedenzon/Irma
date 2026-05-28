"""HTTP surface for /api/v1/brief/*.

Phase 3 only verifies routing and the unavailable-503 shape. Phase 4
tests cache hit/miss and synthesis output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.agents.lead_agent import LeadAgent
from irma_api.config import Settings
from irma_api.routers.brief import router as brief_router
from irma_api.routers.projects import router as projects_router
from irma_api.store.sqlite import SignalStore


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store
    app.state.lead_agent = None  # explicit: synthesis not configured
    app.include_router(brief_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["today", "week", "month", "overview"])
async def test_horizon_routes_return_503_without_agent(client: AsyncClient, path: str) -> None:
    r = await client.get(f"/api/v1/brief/{path}")
    assert r.status_code == 503
    assert r.json()["error"] == "synthesis_unavailable"


class _FakeLLM:
    backend = "fake"
    model = "fake-1"

    async def complete(self, *, system, messages, tools=None, max_tokens=1500, session_id=None):
        from irma_api.agents.llm import TextResult

        return TextResult(
            text=(
                '{"horizon":"day","generated_at":"2026-05-27T12:00:00+00:00",'
                '"focus":[],"project_status":[],"conflicts":[],'
                '"recommendation":"ok","narrative":""}'
            )
        )


@pytest_asyncio.fixture
async def live_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    settings = Settings(
        irma_db_path=tmp_path / "irma.db",
        anthropic_api_key=None,
        anthropic_model="x",
    )
    app.state.store = store
    app.state.lead_agent = LeadAgent(settings=settings, llm=_FakeLLM(), store=store)
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(brief_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
async def test_brief_today_with_project_returns_200(live_client: AsyncClient) -> None:
    r = await live_client.post("/api/v1/projects", json={"name": "Thesis"})
    assert r.status_code == 201
    r2 = await live_client.get("/api/v1/brief/today")
    assert r2.status_code == 200
    assert r2.json()["horizon"] == "day"
