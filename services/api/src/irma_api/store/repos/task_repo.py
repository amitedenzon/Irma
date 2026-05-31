"""Async CRUD for the `task` table."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

import aiosqlite

from irma_api.models.task import (
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    apply_status_transition,
)
from irma_api.store.errors import NotFoundError

_COLUMNS = (
    "id, project_id, title, notes, status, due_date, scheduled_for, "
    "estimated_minutes, created_at, updated_at, completed_at, reminder_uuid"
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _row_to_task(row: aiosqlite.Row) -> Task:
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        notes=row["notes"],
        status=TaskStatus(row["status"]),
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        scheduled_for=(date.fromisoformat(row["scheduled_for"]) if row["scheduled_for"] else None),
        estimated_minutes=row["estimated_minutes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=(datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None),
        reminder_uuid=row["reminder_uuid"],
    )


class TaskRepo:
    """Pure data access for `task` rows."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(self, data: TaskCreate) -> Task:
        now = _now()
        tid = str(uuid.uuid4())
        try:
            await self._conn.execute(
                f"""
                INSERT INTO task ({_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    tid,
                    data.project_id,
                    data.title,
                    data.notes,
                    data.status.value,
                    data.due_date.isoformat() if data.due_date else None,
                    data.scheduled_for.isoformat() if data.scheduled_for else None,
                    data.estimated_minutes,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise NotFoundError("project", data.project_id) from exc
        return await self.get(tid)

    async def get(self, task_id: str) -> Task:
        cur = await self._conn.execute(f"SELECT {_COLUMNS} FROM task WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("task", task_id)
        return _row_to_task(row)

    async def list(
        self,
        *,
        project_id: str | None = None,
        statuses: Iterable[TaskStatus] | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
        due_before: date | None = None,
    ) -> list[Task]:
        where: list[str] = []
        params: list[object] = []
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        if statuses is not None:
            statuses_list = list(statuses)
            placeholders = ", ".join("?" * len(statuses_list))
            where.append(f"status IN ({placeholders})")
            params.extend(s.value for s in statuses_list)
        if scheduled_from is not None:
            where.append("scheduled_for >= ?")
            params.append(scheduled_from.isoformat())
        if scheduled_to is not None:
            where.append("scheduled_for <= ?")
            params.append(scheduled_to.isoformat())
        if due_before is not None:
            where.append("due_date <= ?")
            params.append(due_before.isoformat())

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = (
            f"SELECT {_COLUMNS} FROM task {clause} "
            "ORDER BY due_date IS NULL, due_date, "
            "scheduled_for IS NULL, scheduled_for, created_at"
        )
        cur = await self._conn.execute(sql, params)
        return [_row_to_task(r) for r in await cur.fetchall()]

    async def update(self, task_id: str, patch: TaskUpdate) -> Task:
        existing = await self.get(task_id)
        updates: dict[str, Any] = patch.model_dump(exclude_unset=True)
        if not updates:
            return existing

        new_status = updates.pop("status", None)
        if new_status is not None:
            transitioned = apply_status_transition(
                existing, new_status=TaskStatus(new_status), now=_now()
            )
            updates["status"] = transitioned.status.value
            updates["completed_at"] = (
                transitioned.completed_at.isoformat() if transitioned.completed_at else None
            )

        sets: list[str] = []
        params: list[object] = []
        for key, value in updates.items():
            if key in ("due_date", "scheduled_for"):
                sets.append(f"{key} = ?")
                params.append(value.isoformat() if value else None)
            else:
                sets.append(f"{key} = ?")
                params.append(value)
        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(task_id)

        await self._conn.execute(f"UPDATE task SET {', '.join(sets)} WHERE id = ?", params)
        await self._conn.commit()
        return await self.get(task_id)

    async def delete(self, task_id: str) -> None:
        cur = await self._conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("task", task_id)

    async def set_reminder_uuid(self, task_id: str, uuid: str | None) -> None:
        """Link or unlink a task to/from its EKReminder.calendarItemIdentifier."""
        cur = await self._conn.execute(
            "UPDATE task SET reminder_uuid = ?, updated_at = ? WHERE id = ?",
            (uuid, _now().isoformat(), task_id),
        )
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("task", task_id)

    async def set_project(self, task_id: str, new_project_id: str) -> None:
        """Reattribute a task to a different project (used by the cross-calendar
        move path in the Reminders sync planner)."""
        cur = await self._conn.execute(
            "UPDATE task SET project_id = ?, updated_at = ? WHERE id = ?",
            (new_project_id, _now().isoformat(), task_id),
        )
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("task", task_id)

    async def count_non_done_for_project(self, project_id: str) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) AS n FROM task WHERE project_id = ? AND status != 'done'",
            (project_id,),
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0
