from __future__ import annotations

import aiosqlite
import pytest

from irma_api.integrations.reminders.inbox import INBOX_NAME, ensure_inbox_project
from irma_api.store.migrations import ensure_schema
from irma_api.store.repos.project_repo import ProjectRepo


@pytest.fixture
async def conn(tmp_path):
    async with aiosqlite.connect(tmp_path / "t.db") as c:
        c.row_factory = aiosqlite.Row
        await ensure_schema(c)
        yield c


@pytest.mark.asyncio
async def test_creates_inbox_when_missing(conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(conn)
    inbox = await ensure_inbox_project(repo)
    assert inbox.name == INBOX_NAME
    listed = await repo.list()
    assert any(p.name == INBOX_NAME for p in listed)


@pytest.mark.asyncio
async def test_returns_existing_inbox_when_present(conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(conn)
    first = await ensure_inbox_project(repo)
    second = await ensure_inbox_project(repo)
    assert first.id == second.id
