"""POST /api/v1/brief/email: 503 unconfigured, 200 + status when wired."""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.brief import router as brief_router


@pytest_asyncio.fixture
async def make_client():
    async def _make(job: object | None) -> AsyncClient:
        app = FastAPI()
        app.state.daily_brief_job = job
        app.include_router(brief_router, prefix="/api/v1")
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://t")

    return _make


@pytest.mark.asyncio
async def test_email_503_without_job(make_client) -> None:
    client = await make_client(None)
    async with client:
        r = await client.post("/api/v1/brief/email")
    assert r.status_code == 503
    assert r.json()["error"] == "email_unavailable"


@pytest.mark.asyncio
async def test_email_200_sends(make_client) -> None:
    class _FakeJob:
        def __init__(self) -> None:
            self.forced = False

        async def run_once(self, *, force: bool = False) -> dict[str, object]:
            self.forced = force
            return {"sent": True, "result": "sent (message id fake-9)"}

    job = _FakeJob()
    client = await make_client(job)
    async with client:
        r = await client.post("/api/v1/brief/email")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"
    assert "fake-9" in body["detail"]
    assert job.forced is True
