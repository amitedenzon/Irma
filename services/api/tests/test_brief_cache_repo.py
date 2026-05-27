"""BriefCacheRepo: per-horizon get/put/delete and clear-all."""

from __future__ import annotations

from datetime import datetime

import aiosqlite
import pytest

from irma_api.models.brief import Brief
from irma_api.store.repos.brief_cache_repo import BriefCacheRepo


def _brief(horizon: str = "day", note: str = "x") -> Brief:
    return Brief(
        horizon=horizon,
        generated_at=datetime(2026, 5, 27, 12, 0, 0),
        focus=[],
        project_status=[],
        conflicts=[],
        recommendation=note,
        narrative="",
    )


@pytest.mark.asyncio
async def test_miss_returns_none(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    assert await repo.get("day", inputs_hash="h1") is None


@pytest.mark.asyncio
async def test_put_then_hit(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    b = _brief("day", "today")
    await repo.put("day", inputs_hash="h1", brief=b)
    assert await repo.get("day", inputs_hash="h1") == b


@pytest.mark.asyncio
async def test_hash_mismatch_is_a_miss(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    await repo.put("day", inputs_hash="h1", brief=_brief("day"))
    assert await repo.get("day", inputs_hash="h2") is None


@pytest.mark.asyncio
async def test_put_overwrites(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    await repo.put("day", inputs_hash="h1", brief=_brief("day", "first"))
    await repo.put("day", inputs_hash="h2", brief=_brief("day", "second"))
    hit = await repo.get("day", inputs_hash="h2")
    assert hit is not None
    assert hit.recommendation == "second"


@pytest.mark.asyncio
async def test_clear_all(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    for h in ("day", "week", "month", "all"):
        await repo.put(h, inputs_hash="h", brief=_brief(h))
    await repo.clear()
    for h in ("day", "week", "month", "all"):
        assert await repo.get(h, inputs_hash="h") is None
