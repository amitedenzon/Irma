"""TaskRepo: CRUD, filters, ordering, status auto-stamp, FK enforcement."""

from __future__ import annotations

from datetime import date, datetime

import aiosqlite
import pytest

from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate, TaskStatus, TaskUpdate
from irma_api.store.errors import ConflictError, NotFoundError
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo


async def _make_project(db_conn: aiosqlite.Connection, name: str = "P") -> str:
    repo = ProjectRepo(db_conn)
    p = await repo.create(ProjectCreate(name=name))
    return p.id


@pytest.mark.asyncio
async def test_create_and_get(db_conn: aiosqlite.Connection) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(
        TaskCreate(
            project_id=pid,
            title="Draft results",
            due_date=date(2026, 5, 28),
            scheduled_for=date(2026, 5, 27),
            estimated_minutes=90,
        )
    )
    assert t.id
    assert t.status is TaskStatus.TODO
    assert t.completed_at is None
    fetched = await repo.get(t.id)
    assert fetched == t


@pytest.mark.asyncio
async def test_create_with_missing_project_raises_not_found(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = TaskRepo(db_conn)
    with pytest.raises(NotFoundError):
        await repo.create(TaskCreate(project_id="nope", title="x"))


@pytest.mark.asyncio
async def test_list_filters_by_project(db_conn: aiosqlite.Connection) -> None:
    a = await _make_project(db_conn, "A")
    b = await _make_project(db_conn, "B")
    repo = TaskRepo(db_conn)
    await repo.create(TaskCreate(project_id=a, title="A1"))
    await repo.create(TaskCreate(project_id=b, title="B1"))
    out = await repo.list(project_id=a)
    assert [t.title for t in out] == ["A1"]


@pytest.mark.asyncio
async def test_list_filters_by_status_and_window(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    await repo.create(
        TaskCreate(project_id=pid, title="today",
                   scheduled_for=date(2026, 5, 27))
    )
    await repo.create(
        TaskCreate(project_id=pid, title="next-week",
                   scheduled_for=date(2026, 6, 3))
    )
    today_only = await repo.list(
        project_id=pid,
        scheduled_from=date(2026, 5, 27),
        scheduled_to=date(2026, 5, 27),
    )
    assert [t.title for t in today_only] == ["today"]

    done = await repo.list(project_id=pid, statuses=[TaskStatus.DONE])
    assert done == []


@pytest.mark.asyncio
async def test_list_orders_by_due_then_scheduled_then_created(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    later = await repo.create(
        TaskCreate(project_id=pid, title="due-later",
                   due_date=date(2026, 6, 10))
    )
    sooner = await repo.create(
        TaskCreate(project_id=pid, title="due-sooner",
                   due_date=date(2026, 6, 1))
    )
    no_due = await repo.create(TaskCreate(project_id=pid, title="no-due"))
    out = await repo.list(project_id=pid)
    assert [t.id for t in out] == [sooner.id, later.id, no_due.id]


@pytest.mark.asyncio
async def test_update_status_done_stamps_completed_at(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(TaskCreate(project_id=pid, title="x"))
    updated = await repo.update(t.id, TaskUpdate(status=TaskStatus.DONE))
    assert updated.status is TaskStatus.DONE
    assert isinstance(updated.completed_at, datetime)


@pytest.mark.asyncio
async def test_update_status_out_of_done_clears_completed_at(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(TaskCreate(project_id=pid, title="x"))
    await repo.update(t.id, TaskUpdate(status=TaskStatus.DONE))
    re_open = await repo.update(t.id, TaskUpdate(status=TaskStatus.TODO))
    assert re_open.completed_at is None


@pytest.mark.asyncio
async def test_delete(db_conn: aiosqlite.Connection) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(TaskCreate(project_id=pid, title="x"))
    await repo.delete(t.id)
    with pytest.raises(NotFoundError):
        await repo.get(t.id)


@pytest.mark.asyncio
async def test_count_open_blocks_project_delete(
    db_conn: aiosqlite.Connection,
) -> None:
    """ProjectRepo.delete uses TaskRepo.count_non_done_for_project to decide."""
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    await repo.create(TaskCreate(project_id=pid, title="open"))
    await repo.create(
        TaskCreate(project_id=pid, title="closed", status=TaskStatus.DONE)
    )
    assert await repo.count_non_done_for_project(pid) == 1


@pytest.mark.asyncio
async def test_project_delete_with_attached_tasks_raises_conflict(
    db_conn: aiosqlite.Connection,
) -> None:
    """Via the FK ON DELETE RESTRICT — sqlite raises IntegrityError."""
    pid = await _make_project(db_conn)
    trepo = TaskRepo(db_conn)
    await trepo.create(TaskCreate(project_id=pid, title="x"))
    prepo = ProjectRepo(db_conn)
    with pytest.raises(ConflictError):
        await prepo.delete(pid)
