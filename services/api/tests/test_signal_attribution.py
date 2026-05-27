"""Calendar signals get attributed to projects via keyword match at write."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from irma_api.models.project import ProjectCreate, ProjectStatus, ProjectUpdate
from irma_api.models.signal import Signal
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.sqlite import SignalStore


def _signal(title: str, *, source: str = "calendar") -> Signal:
    return Signal(
        source=source,
        kind="event",
        title=title,
        detail="",
        ts=datetime.now(UTC),
        meta={},
    )


async def _project_ids_for_signals(store: SignalStore) -> list[str | None]:
    cur = await store.connection.execute(
        "SELECT project_id FROM signals ORDER BY id"
    )
    rows = await cur.fetchall()
    return [row["project_id"] for row in rows]


@pytest.mark.asyncio
async def test_calendar_signal_attributes_via_keyword(
    store: SignalStore,
) -> None:
    prepo = ProjectRepo(store.connection)
    await prepo.create(ProjectCreate(name="Thesis", calendar_keywords=["gal"]))
    await store.upsert_signals([_signal("Meeting with Prof. Gal")])
    pids = await _project_ids_for_signals(store)
    assert len(pids) == 1
    assert pids[0] is not None


@pytest.mark.asyncio
async def test_codebase_signal_is_never_attributed(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    await prepo.create(ProjectCreate(name="Thesis", calendar_keywords=["thesis"]))
    await store.upsert_signals([_signal("3 commits in thesis", source="codebase")])
    pids = await _project_ids_for_signals(store)
    assert pids == [None]


@pytest.mark.asyncio
async def test_no_match_yields_null_project(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    await prepo.create(ProjectCreate(name="Thesis", calendar_keywords=["gal"]))
    await store.upsert_signals([_signal("Unrelated event")])
    pids = await _project_ids_for_signals(store)
    assert pids == [None]


@pytest.mark.asyncio
async def test_multi_match_picks_higher_priority(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    low = await prepo.create(
        ProjectCreate(name="LowP", priority=3, calendar_keywords=["lecture"])
    )
    high = await prepo.create(
        ProjectCreate(name="HighP", priority=1, calendar_keywords=["lecture"])
    )
    await store.upsert_signals([_signal("Lecture today")])
    pids = await _project_ids_for_signals(store)
    assert pids == [high.id]
    assert pids != [low.id]


@pytest.mark.asyncio
async def test_archived_project_is_not_matched(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    p = await prepo.create(ProjectCreate(name="X", calendar_keywords=["lab"]))
    await prepo.update(p.id, ProjectUpdate(status=ProjectStatus.ARCHIVED))
    await store.upsert_signals([_signal("Lab meeting")])
    pids = await _project_ids_for_signals(store)
    assert pids == [None]
