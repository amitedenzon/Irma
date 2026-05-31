"""Sync service: snapshot both sides, plan, apply.

Runs via `sync_once()`. Uses an asyncio.Lock + pending_rerun flag to
coalesce concurrent callers: only one sync runs at a time; if a second
caller arrives while a sync is in progress, a single follow-up run is
queued rather than an unbounded backlog.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from irma_api.integrations.reminders.bridge import BridgeError, ReminderBridge
from irma_api.integrations.reminders.inbox import ensure_inbox_project
from irma_api.integrations.reminders.models import BatchOp, ReminderFields
from irma_api.integrations.reminders.planner import (
    HelperCalendarSnap,
    IrmaProjectSnap,
    IrmaSnapshot,
    IrmaTaskSnap,
    SyncPlan,
    plan,
)
from irma_api.models.project import ProjectStatus, ProjectUpdate
from irma_api.models.task import TaskCreate, TaskStatus, TaskUpdate
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

logger = structlog.get_logger(__name__)


@dataclass
class SyncStats:
    # calendar-level
    created_calendars: int = 0
    renamed_calendars: int = 0
    deleted_calendars: int = 0
    unlinked_projects: int = 0
    renamed_projects: int = 0
    # reminder-level
    created_remote: int = 0
    patched_remote: int = 0
    deleted_remote: int = 0
    created_local: int = 0
    patched_local: int = 0
    deleted_local: int = 0
    moved_local: int = 0


class ReminderSyncService:
    def __init__(
        self,
        *,
        project_repo: ProjectRepo,
        task_repo: TaskRepo,
        bridge: ReminderBridge,
        calendar_prefix: str = "Irma · ",
    ) -> None:
        self._projects = project_repo
        self._tasks = task_repo
        self._bridge = bridge
        self._calendar_prefix = calendar_prefix
        self._lock = asyncio.Lock()
        self._pending_rerun = False
        self.last_sync_at: datetime | None = None
        self.last_error: str | None = None

    async def sync_once(self) -> SyncStats:
        if self._lock.locked():
            self._pending_rerun = True
            return SyncStats()
        async with self._lock:
            stats = await self._run_once_locked()
            while self._pending_rerun:
                self._pending_rerun = False
                follow = await self._run_once_locked()
                for field_name in asdict(follow):
                    setattr(stats, field_name, getattr(stats, field_name) + getattr(follow, field_name))
            return stats

    async def _run_once_locked(self) -> SyncStats:
        try:
            await ensure_inbox_project(self._projects)
            irma_snap = await self._snapshot_irma()
            helper_calendars = await self._snapshot_helper()
            sync_plan = plan(irma_snap, helper_calendars, calendar_prefix=self._calendar_prefix)
            stats = await self._apply(sync_plan)
            self.last_sync_at = datetime.now(UTC)
            self.last_error = None
            logger.info("reminders.sync.completed", **asdict(stats))
            return stats
        except BridgeError as exc:
            self.last_error = f"{exc.code}: {exc.message}"
            logger.warning("reminders.sync.failed", code=exc.code, message=exc.message)
            return SyncStats()
        except Exception:
            self.last_error = "internal error"
            logger.exception("reminders.sync.crashed")
            return SyncStats()

    async def _snapshot_irma(self) -> IrmaSnapshot:
        projects = await self._projects.list(
            statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED, ProjectStatus.ARCHIVED]
        )
        tasks = await self._tasks.list()
        return IrmaSnapshot(
            projects=[
                IrmaProjectSnap(
                    id=p.id,
                    name=p.name,
                    status=p.status,
                    reminder_calendar_id=p.reminder_calendar_id,
                    updated_at=p.updated_at,
                )
                for p in projects
            ],
            tasks=[
                IrmaTaskSnap(
                    id=t.id,
                    project_id=t.project_id,
                    title=t.title,
                    status=t.status,
                    reminder_uuid=t.reminder_uuid,
                    updated_at=t.updated_at,
                    due_date=t.due_date,
                    scheduled_for=t.scheduled_for,
                    notes=t.notes,
                )
                for t in tasks
            ],
        )

    async def _snapshot_helper(self) -> list[HelperCalendarSnap]:
        # Fetch ALL calendars so the planner can detect when a linked calendar
        # has had its "Irma · " prefix dropped on the phone (unlink signal).
        # Only fetch reminders for prefix-matched calendars to avoid listing
        # unrelated phone calendars.
        all_cals = await self._bridge.list_calendars(prefix="")
        snaps: list[HelperCalendarSnap] = []
        for c in all_cals:
            if c.title.startswith(self._calendar_prefix):
                reminders = await self._bridge.list(c.calendar_id)
            else:
                reminders = []
            snaps.append(HelperCalendarSnap(
                calendar_id=c.calendar_id, title=c.title, reminders=reminders,
            ))
        return snaps

    async def _apply(self, sync_plan: SyncPlan) -> SyncStats:
        stats = SyncStats()

        # Phase 1 — Structural Irma-side updates (no remote I/O)
        for op in sync_plan.unlink_projects:
            await self._projects.set_reminder_calendar_id(op.irma_project_id, None)
            stats.unlinked_projects += 1

        for op in sync_plan.rename_projects:
            await self._projects.update(op.irma_project_id, ProjectUpdate(name=op.new_name))
            stats.renamed_projects += 1

        # Phase 2 — Calendar mutations
        for op in sync_plan.create_calendars:
            new_id = await self._bridge.ensure_list(op.title)
            await self._projects.set_reminder_calendar_id(op.irma_project_id, new_id)
            stats.created_calendars += 1

        for op in sync_plan.rename_calendars:
            await self._bridge.rename_calendar(op.calendar_id, op.new_title)
            stats.renamed_calendars += 1

        for op in sync_plan.delete_calendars:
            await self._bridge.delete_calendar(op.calendar_id)
            stats.deleted_calendars += 1

        # Phase 3 — Per-calendar reminder batches
        # Group by calendar_id, ordering within each calendar: creates → patches → deletes
        creates_by_cal: dict[str, list[Any]] = defaultdict(list)
        patches_by_cal: dict[str, list[Any]] = defaultdict(list)
        deletes_by_cal: dict[str, list[Any]] = defaultdict(list)

        for op in sync_plan.create_remote_reminders:
            creates_by_cal[op.calendar_id].append(op)
        for op in sync_plan.patch_remote_reminders:
            patches_by_cal[op.calendar_id].append(op)
        for op in sync_plan.delete_remote_reminders:
            deletes_by_cal[op.calendar_id].append(op)

        all_cal_ids = (
            set(creates_by_cal.keys())
            | set(patches_by_cal.keys())
            | set(deletes_by_cal.keys())
        )

        for cal_id in all_cal_ids:
            cr_ops = creates_by_cal.get(cal_id, [])
            pa_ops = patches_by_cal.get(cal_id, [])
            de_ops = deletes_by_cal.get(cal_id, [])

            batch_ops: list[BatchOp] = (
                [BatchOp.create_op(op.fields) for op in cr_ops]
                + [BatchOp.update_op(op.reminder_uuid, op.fields) for op in pa_ops]
                + [BatchOp.delete_op(op.reminder_uuid) for op in de_ops]
            )
            if not batch_ops:
                continue

            results = await self._bridge.batch(cal_id, batch_ops, continue_on_error=True)

            n_creates = len(cr_ops)
            n_patches = len(pa_ops)

            for i, cr_op in enumerate(cr_ops):
                if i < len(results) and results[i].ok and results[i].uuid:
                    await self._tasks.set_reminder_uuid(cr_op.irma_task_id, results[i].uuid)
                    stats.created_remote += 1

            for i in range(n_patches):
                idx = n_creates + i
                if idx < len(results) and results[idx].ok:
                    stats.patched_remote += 1

            for i in range(len(de_ops)):
                idx = n_creates + n_patches + i
                if idx < len(results) and results[idx].ok:
                    stats.deleted_remote += 1

        # Phase 4 — Irma-side reminder mutations (no remote I/O)
        for op in sync_plan.create_local_tasks:
            initial_status = TaskStatus.DONE if op.is_completed else TaskStatus.TODO
            task = await self._tasks.create(
                TaskCreate(
                    project_id=op.project_id,
                    title=op.title,
                    notes=op.notes,
                    due_date=op.due_date,
                    scheduled_for=op.scheduled_for,
                    status=initial_status,
                )
            )
            await self._tasks.set_reminder_uuid(task.id, op.reminder_uuid)
            stats.created_local += 1

        for op in sync_plan.patch_local_tasks:
            update_kwargs: dict[str, Any] = {}
            if op.title is not None:
                update_kwargs["title"] = op.title
            if op.notes is not None:
                update_kwargs["notes"] = op.notes
            if op.due_date is not None:
                update_kwargs["due_date"] = op.due_date
            if op.scheduled_for is not None:
                update_kwargs["scheduled_for"] = op.scheduled_for
            if op.is_completed is not None:
                update_kwargs["status"] = TaskStatus.DONE if op.is_completed else TaskStatus.TODO
            if update_kwargs:
                await self._tasks.update(op.task_id, TaskUpdate(**update_kwargs))
            stats.patched_local += 1

        for op in sync_plan.move_tasks:
            await self._tasks.set_project(op.task_id, op.new_project_id)
            stats.moved_local += 1

        for op in sync_plan.delete_local_tasks:
            await self._tasks.delete(op.task_id)
            stats.deleted_local += 1

        return stats
