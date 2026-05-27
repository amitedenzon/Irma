"""ProjectRepo: CRUD, uniqueness, status filtering, ordering."""

from __future__ import annotations

from datetime import date

import aiosqlite
import pytest

from irma_api.models.project import ProjectCreate, ProjectStatus, ProjectUpdate
from irma_api.store.errors import ConflictError, NotFoundError
from irma_api.store.repos.project_repo import ProjectRepo


@pytest.mark.asyncio
async def test_create_and_get(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    p = await repo.create(
        ProjectCreate(
            name="Thesis",
            description="Bar-Ilan M.Sc",
            calendar_keywords=["gal", "thesis"],
            goals=["Submit draft by 2026-07-15"],
            target_date=date(2026, 7, 15),
            priority=1,
        )
    )
    assert p.id
    assert p.name == "Thesis"
    assert p.calendar_keywords == ["gal", "thesis"]
    fetched = await repo.get(p.id)
    assert fetched == p


@pytest.mark.asyncio
async def test_create_duplicate_name_case_insensitive_conflicts(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProjectRepo(db_conn)
    await repo.create(ProjectCreate(name="Thesis"))
    with pytest.raises(ConflictError):
        await repo.create(ProjectCreate(name="THESIS"))


@pytest.mark.asyncio
async def test_get_missing_raises_not_found(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    with pytest.raises(NotFoundError):
        await repo.get("nope")


@pytest.mark.asyncio
async def test_list_filters_and_orders_by_priority_then_name(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProjectRepo(db_conn)
    await repo.create(ProjectCreate(name="Zeta", priority=3))
    await repo.create(ProjectCreate(name="Alpha", priority=1))
    await repo.create(ProjectCreate(name="Beta", priority=1))
    paused = await repo.create(ProjectCreate(name="Sidekick", priority=2))
    await repo.update(paused.id, ProjectUpdate(status=ProjectStatus.PAUSED))

    active = await repo.list(statuses=[ProjectStatus.ACTIVE])
    assert [p.name for p in active] == ["Alpha", "Beta", "Zeta"]

    paused_list = await repo.list(statuses=[ProjectStatus.PAUSED])
    assert [p.name for p in paused_list] == ["Sidekick"]

    both = await repo.list(statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED])
    assert {p.name for p in both} == {"Alpha", "Beta", "Zeta", "Sidekick"}


@pytest.mark.asyncio
async def test_update_partial(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    p = await repo.create(ProjectCreate(name="Thesis", priority=2))
    updated = await repo.update(p.id, ProjectUpdate(priority=1, goals=["Draft", "Defense"]))
    assert updated.priority == 1
    assert updated.goals == ["Draft", "Defense"]
    assert updated.name == "Thesis"
    assert updated.updated_at >= p.updated_at


@pytest.mark.asyncio
async def test_update_to_duplicate_name_conflicts(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProjectRepo(db_conn)
    await repo.create(ProjectCreate(name="Thesis"))
    other = await repo.create(ProjectCreate(name="MIT"))
    with pytest.raises(ConflictError):
        await repo.update(other.id, ProjectUpdate(name="thesis"))


@pytest.mark.asyncio
async def test_delete(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    p = await repo.create(ProjectCreate(name="x"))
    await repo.delete(p.id)
    with pytest.raises(NotFoundError):
        await repo.get(p.id)


@pytest.mark.asyncio
async def test_delete_missing_raises(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    with pytest.raises(NotFoundError):
        await repo.delete("nope")
