"""Pure-function reconciliation planner. No I/O, no async, no clock.

The sync engine calls ``plan(...)`` between the snapshot and apply passes.
Output is a :class:`SyncPlan` — a description of mutations on both sides —
that the engine then executes idempotently.

Architecture: Projects map 1:1 to ``EKCalendar``s named ``Irma · <name>``;
Tasks are flat reminders within their project's calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from irma_api.integrations.reminders.models import HelperReminder, ReminderFields
from irma_api.models.project import ProjectStatus
from irma_api.models.task import TaskStatus

_DEFAULT_CALENDAR_PREFIX = "Irma · "
_DEFAULT_PAUSED_PREFIX = "⏸ "


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IrmaProjectSnap:
    id: str
    name: str
    status: ProjectStatus
    reminder_calendar_id: str | None
    updated_at: datetime


@dataclass(frozen=True)
class IrmaTaskSnap:
    id: str
    project_id: str
    title: str
    status: TaskStatus
    reminder_uuid: str | None
    updated_at: datetime
    due_date: date | None = None
    scheduled_for: date | None = None
    notes: str = ""


@dataclass(frozen=True)
class IrmaSnapshot:
    projects: list[IrmaProjectSnap]
    tasks: list[IrmaTaskSnap]


@dataclass(frozen=True)
class HelperCalendarSnap:
    """One Irma-prefixed calendar on the phone + its reminders."""

    calendar_id: str
    title: str
    reminders: list[HelperReminder]


# ---------------------------------------------------------------------------
# Calendar-level operations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateCalendar:
    irma_project_id: str
    title: str


@dataclass(frozen=True)
class RenameCalendar:
    calendar_id: str
    new_title: str


@dataclass(frozen=True)
class DeleteCalendar:
    calendar_id: str


@dataclass(frozen=True)
class UnlinkProject:
    """Clear ``Project.reminder_calendar_id`` without touching the phone calendar."""

    irma_project_id: str


@dataclass(frozen=True)
class RenameProject:
    """Phone-side calendar rename propagated back to ``Project.name``."""

    irma_project_id: str
    new_name: str


# ---------------------------------------------------------------------------
# Reminder-level operations (remote = Reminders side, local = Irma DB)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateRemoteReminder:
    irma_task_id: str
    calendar_id: str
    fields: ReminderFields


@dataclass(frozen=True)
class PatchRemoteReminder:
    irma_task_id: str
    calendar_id: str
    reminder_uuid: str
    fields: ReminderFields


@dataclass(frozen=True)
class DeleteRemoteReminder:
    calendar_id: str
    reminder_uuid: str


@dataclass(frozen=True)
class CreateLocalTask:
    project_id: str
    reminder_uuid: str
    title: str
    notes: str
    due_date: date | None
    scheduled_for: date | None
    is_completed: bool


@dataclass(frozen=True)
class PatchLocalTask:
    task_id: str
    title: str | None = None
    notes: str | None = None
    due_date: date | None = None
    scheduled_for: date | None = None
    is_completed: bool | None = None


@dataclass(frozen=True)
class DeleteLocalTask:
    task_id: str


@dataclass(frozen=True)
class MoveTask:
    """Task moved between Irma projects because its reminder lives in a different calendar now."""

    task_id: str
    new_project_id: str


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass
class SyncPlan:
    create_calendars: list[CreateCalendar] = field(default_factory=list)
    rename_calendars: list[RenameCalendar] = field(default_factory=list)
    delete_calendars: list[DeleteCalendar] = field(default_factory=list)
    unlink_projects: list[UnlinkProject] = field(default_factory=list)
    rename_projects: list[RenameProject] = field(default_factory=list)

    create_remote_reminders: list[CreateRemoteReminder] = field(default_factory=list)
    patch_remote_reminders: list[PatchRemoteReminder] = field(default_factory=list)
    delete_remote_reminders: list[DeleteRemoteReminder] = field(default_factory=list)

    create_local_tasks: list[CreateLocalTask] = field(default_factory=list)
    patch_local_tasks: list[PatchLocalTask] = field(default_factory=list)
    delete_local_tasks: list[DeleteLocalTask] = field(default_factory=list)

    move_tasks: list[MoveTask] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _expected_title(
    name: str, status: ProjectStatus, prefix: str, paused_prefix: str
) -> str:
    if status is ProjectStatus.PAUSED:
        return f"{prefix}{paused_prefix}{name}"
    return f"{prefix}{name}"


def _strip_prefixes(
    title: str, calendar_prefix: str, paused_prefix: str
) -> str | None:
    """Return the inner name if `title` starts with `calendar_prefix`,
    stripping any leading `paused_prefix`. None if the title doesn't have
    the calendar prefix at all (i.e., user dropped it on the phone)."""
    if not title.startswith(calendar_prefix):
        return None
    inner = title[len(calendar_prefix) :]
    if inner.startswith(paused_prefix):
        inner = inner[len(paused_prefix) :]
    return inner


def _task_to_fields(t: IrmaTaskSnap) -> ReminderFields:
    return ReminderFields(
        title=t.title,
        notes=t.notes,
        due_date=t.due_date,
        start_date=t.scheduled_for,
        is_completed=(t.status is TaskStatus.DONE),
    )


def _diff_fields_for_remote_patch(
    task: IrmaTaskSnap, rem: HelperReminder
) -> ReminderFields | None:
    """Build a ReminderFields with only the fields where the Irma side
    differs from the helper side. Return None if nothing differs."""
    fields = ReminderFields(
        title=task.title if task.title != rem.title else None,
        notes=task.notes if task.notes != rem.notes else None,
        due_date=task.due_date if task.due_date != rem.due_date else None,
        start_date=task.scheduled_for if task.scheduled_for != rem.start_date else None,
        is_completed=(
            (task.status is TaskStatus.DONE)
            if (task.status is TaskStatus.DONE) != rem.is_completed
            else None
        ),
    )
    dumped = fields.model_dump(exclude_none=True)
    return fields if dumped else None


def _local_patch_for(task: IrmaTaskSnap, rem: HelperReminder) -> PatchLocalTask | None:
    """Build a PatchLocalTask with only the fields where the remote
    differs from Irma. Return None if nothing differs."""
    patch = PatchLocalTask(
        task_id=task.id,
        title=rem.title if rem.title != task.title else None,
        notes=rem.notes if rem.notes != task.notes else None,
        due_date=rem.due_date if rem.due_date != task.due_date else None,
        scheduled_for=rem.start_date if rem.start_date != task.scheduled_for else None,
        is_completed=(
            rem.is_completed
            if rem.is_completed != (task.status is TaskStatus.DONE)
            else None
        ),
    )
    has_change = any(
        v is not None
        for v in (
            patch.title,
            patch.notes,
            patch.due_date,
            patch.scheduled_for,
            patch.is_completed,
        )
    )
    return patch if has_change else None


def plan(
    irma: IrmaSnapshot,
    helper_calendars: list[HelperCalendarSnap],
    *,
    calendar_prefix: str = _DEFAULT_CALENDAR_PREFIX,
    paused_prefix: str = _DEFAULT_PAUSED_PREFIX,
) -> SyncPlan:
    """Compute the reconciliation plan. Pure function."""

    sp = SyncPlan()

    cal_by_id: dict[str, HelperCalendarSnap] = {c.calendar_id: c for c in helper_calendars}
    proj_by_calendar_id: dict[str, IrmaProjectSnap] = {
        p.reminder_calendar_id: p
        for p in irma.projects
        if p.reminder_calendar_id is not None
    }
    proj_by_id: dict[str, IrmaProjectSnap] = {p.id: p for p in irma.projects}

    # Global index: where (which calendar id) is each reminder uuid?
    rem_to_calendar: dict[str, str] = {}
    for c in helper_calendars:
        for r in c.reminders:
            rem_to_calendar[r.uuid] = c.calendar_id

    # ------------------------------------------------------------------
    # Pass 1 — calendar reconcile.
    # ------------------------------------------------------------------
    # Track per-project whether this project's calendar is in a state where
    # reminder reconcile should run for it. Key: project_id, value: the
    # calendar_id to use (after any same-cycle changes).
    project_calendars_for_reminder_pass: dict[str, str] = {}

    for proj in irma.projects:
        expected = _expected_title(proj.name, proj.status, calendar_prefix, paused_prefix)

        if proj.status is ProjectStatus.ARCHIVED:
            if proj.reminder_calendar_id and proj.reminder_calendar_id in cal_by_id:
                sp.delete_calendars.append(
                    DeleteCalendar(calendar_id=proj.reminder_calendar_id)
                )
            continue

        # Active or Paused project.
        if proj.reminder_calendar_id is None:
            sp.create_calendars.append(
                CreateCalendar(irma_project_id=proj.id, title=expected)
            )
            continue

        phone_cal = cal_by_id.get(proj.reminder_calendar_id)
        if phone_cal is None:
            # Calendar was deleted on the phone — recreate.
            sp.create_calendars.append(
                CreateCalendar(irma_project_id=proj.id, title=expected)
            )
            continue

        # Calendar is linked on both sides.
        inner = _strip_prefixes(phone_cal.title, calendar_prefix, paused_prefix)
        if inner is None:
            # User dropped the prefix on the phone — treat as unlink.
            sp.unlink_projects.append(UnlinkProject(irma_project_id=proj.id))
            continue

        # Phone has prefix; reconcile the inner name (phone wins for rename)
        # and the pause-marker (Irma authoritative).
        if inner != proj.name:
            sp.rename_projects.append(
                RenameProject(irma_project_id=proj.id, new_name=inner)
            )
            # Recompute expected against the new name.
            expected = _expected_title(
                inner, proj.status, calendar_prefix, paused_prefix
            )

        if phone_cal.title != expected:
            sp.rename_calendars.append(
                RenameCalendar(
                    calendar_id=proj.reminder_calendar_id, new_title=expected
                )
            )

        project_calendars_for_reminder_pass[proj.id] = proj.reminder_calendar_id

    # ------------------------------------------------------------------
    # Pass 2 — per-project reminder reconcile.
    # ------------------------------------------------------------------
    irma_tasks_by_uuid: dict[str, IrmaTaskSnap] = {
        t.reminder_uuid: t for t in irma.tasks if t.reminder_uuid is not None
    }

    # Tasks grouped by their owning project, but ONLY for projects whose
    # calendar is linked + active in this sync round.
    tasks_by_project: dict[str, list[IrmaTaskSnap]] = {}
    for t in irma.tasks:
        if t.project_id in project_calendars_for_reminder_pass:
            tasks_by_project.setdefault(t.project_id, []).append(t)

    for project_id, cal_id in project_calendars_for_reminder_pass.items():
        phone_cal = cal_by_id[cal_id]
        cal_rems_by_uuid = {r.uuid: r for r in phone_cal.reminders}

        # 2a. Iterate Irma tasks in this project.
        for task in tasks_by_project.get(project_id, []):
            if task.reminder_uuid is None:
                sp.create_remote_reminders.append(
                    CreateRemoteReminder(
                        irma_task_id=task.id,
                        calendar_id=cal_id,
                        fields=_task_to_fields(task),
                    )
                )
                continue

            rem = cal_rems_by_uuid.get(task.reminder_uuid)
            if rem is not None:
                # Both sides have it in this calendar → last-write-wins by ts.
                if rem.last_modified > task.updated_at:
                    local = _local_patch_for(task, rem)
                    if local is not None:
                        sp.patch_local_tasks.append(local)
                else:
                    remote = _diff_fields_for_remote_patch(task, rem)
                    if remote is not None:
                        sp.patch_remote_reminders.append(
                            PatchRemoteReminder(
                                irma_task_id=task.id,
                                calendar_id=cal_id,
                                reminder_uuid=task.reminder_uuid,
                                fields=remote,
                            )
                        )
                continue

            # task.reminder_uuid is not in this calendar.
            other_cal_id = rem_to_calendar.get(task.reminder_uuid)
            if other_cal_id is not None and other_cal_id in proj_by_calendar_id:
                dest_proj = proj_by_calendar_id[other_cal_id]
                if dest_proj.id != task.project_id:
                    sp.move_tasks.append(
                        MoveTask(task_id=task.id, new_project_id=dest_proj.id)
                    )
                continue

            # Not found anywhere we sync → phone deleted it.
            sp.delete_local_tasks.append(DeleteLocalTask(task_id=task.id))

        # 2b. Iterate this calendar's reminders to find phone-only creates.
        for rem in phone_cal.reminders:
            if rem.uuid in irma_tasks_by_uuid:
                continue  # Already handled in 2a or owned by another project.
            sp.create_local_tasks.append(
                CreateLocalTask(
                    project_id=project_id,
                    reminder_uuid=rem.uuid,
                    title=rem.title,
                    notes=rem.notes,
                    due_date=rem.due_date,
                    scheduled_for=rem.start_date,
                    is_completed=rem.is_completed,
                )
            )

    return sp
