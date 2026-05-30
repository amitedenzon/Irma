from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from irma_api.integrations.reminders.models import HelperReminder
from irma_api.integrations.reminders.planner import (
    HelperCalendarSnap,
    IrmaProjectSnap,
    IrmaSnapshot,
    IrmaTaskSnap,
    plan,
)
from irma_api.models.project import ProjectStatus
from irma_api.models.task import TaskStatus

T0 = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=1)
T2 = T0 + timedelta(minutes=2)


def _proj(
    *, pid: str, name: str = "Alpha",
    cal_id: str | None = None,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    updated: datetime = T0,
) -> IrmaProjectSnap:
    return IrmaProjectSnap(
        id=pid, name=name, status=status,
        reminder_calendar_id=cal_id, updated_at=updated,
    )


def _task(
    *, tid: str, pid: str, title: str = "t",
    status: TaskStatus = TaskStatus.TODO,
    uuid: str | None = None, updated: datetime = T0,
    due: date | None = None, sched: date | None = None,
    notes: str = "",
) -> IrmaTaskSnap:
    return IrmaTaskSnap(
        id=tid, project_id=pid, title=title, status=status,
        reminder_uuid=uuid, updated_at=updated,
        due_date=due, scheduled_for=sched, notes=notes,
    )


def _rem(
    *, uuid: str, title: str = "r",
    completed: bool = False, modified: datetime = T0,
    due: date | None = None, start: date | None = None,
    notes: str = "",
) -> HelperReminder:
    return HelperReminder(
        uuid=uuid, title=title, notes=notes,
        due_date=due, start_date=start,
        is_completed=completed, completion_date=None,
        last_modified=modified,
    )


def _cal(
    *, cid: str, title: str, reminders: list[HelperReminder] | None = None,
) -> HelperCalendarSnap:
    return HelperCalendarSnap(
        calendar_id=cid, title=title, reminders=reminders or [],
    )


# --- Calendar-level reconcile -------------------------------------------


def test_active_project_with_no_calendar_creates_one() -> None:
    snap = IrmaSnapshot(projects=[_proj(pid="P1", name="Alpha")], tasks=[])
    p = plan(snap, helper_calendars=[])
    assert len(p.create_calendars) == 1
    op = p.create_calendars[0]
    assert op.irma_project_id == "P1"
    assert op.title == "Irma · Alpha"
    assert p.create_remote_reminders == []


def test_archived_project_with_linked_calendar_deletes_it() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", cal_id="CAL-A", status=ProjectStatus.ARCHIVED)],
        tasks=[],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.delete_calendars) == 1
    assert p.delete_calendars[0].calendar_id == "CAL-A"


def test_paused_project_renames_calendar_to_add_prefix() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A",
                        status=ProjectStatus.PAUSED)],
        tasks=[],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.rename_calendars) == 1
    assert p.rename_calendars[0].new_title == "Irma · ⏸ Alpha"
    assert p.rename_projects == []


def test_phone_renamed_calendar_renames_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Beta")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.rename_projects) == 1
    assert p.rename_projects[0].irma_project_id == "P1"
    assert p.rename_projects[0].new_name == "Beta"
    assert p.rename_calendars == []


def test_phone_dropped_prefix_unlinks_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1")],
    )
    cals = [
        _cal(cid="CAL-A", title="Custom Name",
             reminders=[_rem(uuid="REM-T1", title="x")]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.unlink_projects) == 1
    assert p.unlink_projects[0].irma_project_id == "P1"
    assert p.patch_remote_reminders == []
    assert p.patch_local_tasks == []


def test_phone_deleted_calendar_recreates_it_for_active_project() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[],
    )
    p = plan(snap, helper_calendars=[])
    assert len(p.create_calendars) == 1
    assert p.create_calendars[0].title == "Irma · Alpha"


def test_phone_calendar_without_matching_project_is_ignored() -> None:
    snap = IrmaSnapshot(projects=[], tasks=[])
    cals = [
        _cal(cid="CAL-X", title="Irma · Stranger",
             reminders=[_rem(uuid="REM-1", title="ignored")]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert p.create_calendars == []
    assert p.create_local_tasks == []
    assert p.delete_calendars == []


# --- Reminder-level reconcile -------------------------------------------


def test_irma_only_task_with_linked_calendar_creates_remote_reminder() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", title="hello")],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha")]
    p = plan(snap, helper_calendars=cals)
    assert len(p.create_remote_reminders) == 1
    op = p.create_remote_reminders[0]
    assert op.irma_task_id == "T1"
    assert op.calendar_id == "CAL-A"
    assert op.fields.title == "hello"


def test_both_sides_match_no_ops() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", title="match", updated=T0)],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-T1", title="match", modified=T0),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert p.patch_remote_reminders == []
    assert p.patch_local_tasks == []
    assert p.create_remote_reminders == []
    assert p.create_local_tasks == []


def test_phone_newer_patches_local() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", title="old", updated=T0)],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-T1", title="new", modified=T1),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.patch_local_tasks) == 1
    op = p.patch_local_tasks[0]
    assert op.task_id == "T1"
    assert op.title == "new"


def test_irma_newer_patches_remote() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1", title="new", updated=T2)],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-T1", title="old", modified=T1),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.patch_remote_reminders) == 1
    op = p.patch_remote_reminders[0]
    assert op.reminder_uuid == "REM-T1"
    assert op.fields.title == "new"


def test_phone_deleted_reminder_deletes_local() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-DELETED")],
    )
    cals = [_cal(cid="CAL-A", title="Irma · Alpha", reminders=[])]
    p = plan(snap, helper_calendars=cals)
    assert len(p.delete_local_tasks) == 1
    assert p.delete_local_tasks[0].task_id == "T1"


def test_phone_moved_reminder_to_other_calendar_moves_local() -> None:
    snap = IrmaSnapshot(
        projects=[
            _proj(pid="P1", name="Alpha", cal_id="CAL-A"),
            _proj(pid="P2", name="Beta",  cal_id="CAL-B"),
        ],
        tasks=[_task(tid="T1", pid="P1", uuid="REM-T1")],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[]),
        _cal(cid="CAL-B", title="Irma · Beta", reminders=[
            _rem(uuid="REM-T1"),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.move_tasks) == 1
    assert p.move_tasks[0].task_id == "T1"
    assert p.move_tasks[0].new_project_id == "P2"
    assert p.delete_local_tasks == []


def test_phone_created_reminder_in_known_calendar_creates_local_task() -> None:
    snap = IrmaSnapshot(
        projects=[_proj(pid="P1", name="Alpha", cal_id="CAL-A")],
        tasks=[],
    )
    cals = [
        _cal(cid="CAL-A", title="Irma · Alpha", reminders=[
            _rem(uuid="REM-X", title="from-phone"),
        ]),
    ]
    p = plan(snap, helper_calendars=cals)
    assert len(p.create_local_tasks) == 1
    op = p.create_local_tasks[0]
    assert op.project_id == "P1"
    assert op.reminder_uuid == "REM-X"
    assert op.title == "from-phone"
