from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from irma_api.app import create_app


@pytest.fixture
async def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "test.db"))
    from irma_api.config import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, app


@pytest.mark.asyncio
async def test_link_succeeds_when_helper_grants(client) -> None:
    c, app = client
    fake_bridge = MagicMock()
    fake_bridge.request_access = AsyncMock(return_value=True)
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock()
    app.state.reminder_bridge = fake_bridge
    app.state.reminder_sync_factory = lambda: fake_sync

    resp = await c.post("/api/v1/integrations/reminders/link")
    assert resp.status_code == 200
    assert resp.json()["linked"] is True
    assert app.state.settings.reminders_linked is True
    fake_sync.sync_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_returns_403_when_denied(client) -> None:
    c, app = client
    fake_bridge = MagicMock()
    fake_bridge.request_access = AsyncMock(return_value=False)
    app.state.reminder_bridge = fake_bridge
    app.state.reminder_sync_factory = lambda: MagicMock()

    resp = await c.post("/api/v1/integrations/reminders/link")
    assert resp.status_code == 403
    assert app.state.settings.reminders_linked is False


@pytest.mark.asyncio
async def test_sync_now_returns_stats(client) -> None:
    c, app = client
    fake_sync = MagicMock()
    fake_sync.sync_once = AsyncMock(
        return_value=type("S", (), {
            "created_calendars": 1, "renamed_calendars": 0, "deleted_calendars": 0,
            "unlinked_projects": 0, "renamed_projects": 0,
            "created_remote": 2, "patched_remote": 0, "deleted_remote": 0,
            "created_local": 0, "patched_local": 0, "deleted_local": 0,
            "moved_local": 0,
        })()
    )
    app.state.reminder_sync = fake_sync

    resp = await c.post("/api/v1/integrations/reminders/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["created_calendars"] == 1
    assert body["created_remote"] == 2


@pytest.mark.asyncio
async def test_sync_when_unlinked_returns_409(client) -> None:
    c, app = client
    app.state.reminder_sync = None
    resp = await c.post("/api/v1/integrations/reminders/sync")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_unlink_clears_linkage(client) -> None:
    c, app = client
    app.state.settings.reminders_linked = True
    conn = app.state.store.connection
    await conn.execute(
        "INSERT INTO project (id, name, name_lower, status, priority, "
        "calendar_keywords, goals, created_at, updated_at, reminder_calendar_id) "
        "VALUES ('P1', 'Alpha', 'alpha', 'active', 2, '[]', '[]', "
        "'2026-05-30T12:00:00', '2026-05-30T12:00:00', 'CAL-A')"
    )
    await conn.execute(
        "INSERT INTO task (id, project_id, title, notes, status, "
        "created_at, updated_at, reminder_uuid) "
        "VALUES ('T1', 'P1', 'hello', '', 'todo', "
        "'2026-05-30T12:00:00', '2026-05-30T12:00:00', 'REM-T1')"
    )
    await conn.commit()

    resp = await c.delete("/api/v1/integrations/reminders/link")
    assert resp.status_code == 204
    assert app.state.settings.reminders_linked is False

    cur = await conn.execute(
        "SELECT reminder_calendar_id FROM project WHERE id = 'P1'"
    )
    row = await cur.fetchone()
    assert row[0] is None

    cur = await conn.execute(
        "SELECT reminder_uuid FROM task WHERE id = 'T1'"
    )
    row = await cur.fetchone()
    assert row[0] is None
