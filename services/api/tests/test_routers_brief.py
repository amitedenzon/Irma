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

from irma_api.routers.brief import router as brief_router
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
async def test_horizon_routes_return_503_without_agent(
    client: AsyncClient, path: str
) -> None:
    r = await client.get(f"/api/v1/brief/{path}")
    assert r.status_code == 503
    assert r.json()["error"] == "synthesis_unavailable"
