"""SnapshotRepo: upsert idempotency + latest-before baseline lookup."""

from __future__ import annotations

from datetime import date

import aiosqlite
import pytest

from irma_api.store.repos.snapshot_repo import SnapshotRepo


@pytest.mark.asyncio
async def test_get_miss_returns_none(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    assert await repo.get(date(2026, 5, 30)) is None


@pytest.mark.asyncio
async def test_upsert_then_get(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    await repo.upsert(
        date(2026, 5, 30),
        per_project_counts={"p1": {"open": 2, "done": 1}},
        completed_task_ids=["t9"],
    )
    snap = await repo.get(date(2026, 5, 30))
    assert snap is not None
    assert snap.per_project_counts == {"p1": {"open": 2, "done": 1}}
    assert snap.completed_task_ids == ["t9"]


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_date(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    await repo.upsert(date(2026, 5, 30), per_project_counts={}, completed_task_ids=[])
    await repo.upsert(
        date(2026, 5, 30),
        per_project_counts={"p1": {"open": 0, "done": 3}},
        completed_task_ids=["a", "b", "c"],
    )
    snap = await repo.get(date(2026, 5, 30))
    assert snap is not None
    assert snap.completed_task_ids == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_latest_before_picks_most_recent_prior(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    await repo.upsert(date(2026, 5, 28), per_project_counts={}, completed_task_ids=["x"])
    await repo.upsert(date(2026, 5, 29), per_project_counts={}, completed_task_ids=["y"])
    await repo.upsert(date(2026, 5, 30), per_project_counts={}, completed_task_ids=["z"])
    baseline = await repo.latest_before(date(2026, 5, 30))
    assert baseline is not None
    assert baseline.snapshot_date == date(2026, 5, 29)
    assert baseline.completed_task_ids == ["y"]


@pytest.mark.asyncio
async def test_latest_before_none_when_empty(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    assert await repo.latest_before(date(2026, 5, 30)) is None
