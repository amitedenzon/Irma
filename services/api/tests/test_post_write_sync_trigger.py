from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from irma_api.app import create_app


@pytest.mark.asyncio
async def test_create_project_triggers_sync(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "test.db"))
    from irma_api.config import get_settings
    get_settings.cache_clear()
    app = create_app()
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            app.state.reminder_sync = fake_sync
            resp = await c.post(
                "/api/v1/projects",
                json={"name": "test-sync-trigger"},
            )
            assert resp.status_code == 201
            for _ in range(20):
                if fake_sync.sync_once.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
            fake_sync.sync_once.assert_awaited()


@pytest.mark.asyncio
async def test_complete_task_triggers_sync(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "test.db"))
    from irma_api.config import get_settings
    get_settings.cache_clear()
    app = create_app()
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            app.state.reminder_sync = fake_sync
            p = await c.post("/api/v1/projects", json={"name": "trigger-via-task"})
            pid = p.json()["id"]
            t = await c.post(
                "/api/v1/tasks", json={"project_id": pid, "title": "x"}
            )
            tid = t.json()["id"]
            fake_sync.sync_once.reset_mock()
            await c.post(f"/api/v1/tasks/{tid}/complete")
            for _ in range(20):
                if fake_sync.sync_once.await_count >= 1:
                    break
                await asyncio.sleep(0.05)
            fake_sync.sync_once.assert_awaited()
