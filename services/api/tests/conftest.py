"""Shared pytest fixtures.

Provides:
- `_reset_settings_cache` (autouse): clears the @lru_cache on get_settings().
- `db_conn`: a fresh in-memory aiosqlite connection with the schema applied.
- `store`: a connected SignalStore backed by a temp file DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from irma_api.store.migrations import ensure_schema
from irma_api.store.sqlite import SignalStore


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from irma_api.config import get_settings

    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db_conn() -> AsyncIterator[aiosqlite.Connection]:
    """Fresh in-memory aiosqlite connection with the schema applied."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = aiosqlite.Row
    await ensure_schema(conn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[SignalStore]:
    """A connected SignalStore backed by a fresh file DB per test."""
    s = SignalStore(tmp_path / "irma.db")
    await s.connect()
    try:
        yield s
    finally:
        await s.close()
