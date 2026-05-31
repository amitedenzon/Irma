from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import aiosqlite
import pytest

from irma_api.integrations.reminders.bridge import ReminderBridge
from irma_api.integrations.reminders.inbox import INBOX_NAME
from irma_api.integrations.reminders.models import BatchOp, ReminderFields
from irma_api.integrations.reminders.sync import ReminderSyncService, SyncStats
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate
from irma_api.store.migrations import ensure_schema
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

FAKE = Path(__file__).parent / "fixtures" / "fake_helper.py"


@pytest.fixture
async def conn(tmp_path):
    async with aiosqlite.connect(tmp_path / "t.db") as c:
        c.row_factory = aiosqlite.Row
        await ensure_schema(c)
        yield c


def _bridge(tmp_path: Path) -> ReminderBridge:
    return ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(FAKE),),
        env={"FAKE_HELPER_STATE": str(tmp_path / "state.json")},
    )


def _svc(conn, bridge) -> ReminderSyncService:
    return ReminderSyncService(
        project_repo=ProjectRepo(conn),
        task_repo=TaskRepo(conn),
        bridge=bridge,
    )


@pytest.mark.asyncio
async def test_first_sync_creates_one_calendar_per_project_and_pushes_tasks(
    conn, tmp_path,
) -> None:
    repo = ProjectRepo(conn)
    tasks = TaskRepo(conn)
    p = await repo.create(ProjectCreate(name="Alpha"))
    await tasks.create(TaskCreate(project_id=p.id, title="hello"))

    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    # First sync: creates Inbox project row + "Irma · Inbox" calendar +
    # "Irma · Alpha" calendar. Tasks created in the calendar after that.
    stats_1 = await svc.sync_once()
    assert stats_1.created_calendars == 2  # Alpha + Inbox
    # Reminder creation may be deferred to a second pass because Phase 2
    # only just discovered the calendar ids. Acceptable per the algorithm.

    stats_2 = await svc.sync_once()
    assert stats_2.created_remote >= 1   # the "hello" task is now in CAL-Alpha

    refreshed_proj = await repo.get(p.id)
    assert refreshed_proj.reminder_calendar_id is not None

    # Tasks have reminder_uuid
    [refreshed_task] = await tasks.list(project_id=p.id)
    assert refreshed_task.reminder_uuid is not None

    # Helper-side: "Irma · Alpha" calendar contains a "hello" reminder
    cals = await bridge.list_calendars("Irma · ")
    alpha = next(c for c in cals if c.title == "Irma · Alpha")
    rems = await bridge.list(alpha.calendar_id)
    assert any(r.title == "hello" for r in rems)


@pytest.mark.asyncio
async def test_phone_created_reminder_in_alpha_creates_task(
    conn, tmp_path,
) -> None:
    repo = ProjectRepo(conn)
    tasks = TaskRepo(conn)
    p = await repo.create(ProjectCreate(name="Alpha"))

    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    # Push project → creates calendar, sets reminder_calendar_id.
    await svc.sync_once()
    refreshed_proj = await repo.get(p.id)
    cal_id = refreshed_proj.reminder_calendar_id
    assert cal_id is not None

    # Phone-side adds a reminder directly to that calendar.
    await bridge.batch(cal_id, [BatchOp.create_op(ReminderFields(title="from-phone"))])

    # Next sync pulls it as a Task in Alpha.
    stats = await svc.sync_once()
    assert stats.created_local == 1
    assert any(t.title == "from-phone" for t in await tasks.list(project_id=p.id))


@pytest.mark.asyncio
async def test_phone_dropped_prefix_unlinks_project_without_deleting(
    conn, tmp_path,
) -> None:
    repo = ProjectRepo(conn)
    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    p = await repo.create(ProjectCreate(name="Alpha"))
    await svc.sync_once()
    cal_id = (await repo.get(p.id)).reminder_calendar_id
    assert cal_id is not None

    # User renames the calendar on the phone to drop the prefix.
    await bridge.rename_calendar(cal_id, "Just Alpha")

    stats = await svc.sync_once()
    assert stats.unlinked_projects == 1
    assert (await repo.get(p.id)).reminder_calendar_id is None

    # The phone-side calendar still exists (we didn't delete it).
    titles = [c.title for c in await bridge.list_calendars("")]
    assert "Just Alpha" in titles


@pytest.mark.asyncio
async def test_archived_project_deletes_its_calendar(conn, tmp_path) -> None:
    from irma_api.models.project import ProjectStatus, ProjectUpdate

    repo = ProjectRepo(conn)
    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)

    p = await repo.create(ProjectCreate(name="Alpha"))
    await svc.sync_once()
    cal_id = (await repo.get(p.id)).reminder_calendar_id
    assert cal_id is not None

    # Archive in Irma → next sync deletes the calendar on phone.
    await repo.update(p.id, ProjectUpdate(status=ProjectStatus.ARCHIVED))

    stats = await svc.sync_once()
    assert stats.deleted_calendars == 1
    # Verify calendar gone
    cals = await bridge.list_calendars("Irma · ")
    assert all(c.calendar_id != cal_id for c in cals)


@pytest.mark.asyncio
async def test_coalescing_rerun_flag(conn, tmp_path, monkeypatch) -> None:
    bridge = _bridge(tmp_path)
    svc = _svc(conn, bridge)
    calls = 0
    original = svc._run_once_locked

    async def counting() -> SyncStats:
        nonlocal calls
        calls += 1
        return await original()

    monkeypatch.setattr(svc, "_run_once_locked", counting)

    await asyncio.gather(svc.sync_once(), svc.sync_once(), svc.sync_once())
    # First call runs; concurrent calls bounce off the lock, but the rerun
    # flag triggers exactly one follow-up.
    assert calls == 2
