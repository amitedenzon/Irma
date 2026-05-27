"""Async CRUD for the `project` table."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

import aiosqlite

from irma_api.models.project import (
    Project,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
)
from irma_api.store.errors import ConflictError, NotFoundError

_COLUMNS = (
    "id, name, description, status, priority, "
    "calendar_keywords, goals, target_date, created_at, updated_at"
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _row_to_project(row: aiosqlite.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        status=ProjectStatus(row["status"]),
        priority=row["priority"],
        calendar_keywords=json.loads(row["calendar_keywords"]),
        goals=json.loads(row["goals"]),
        target_date=(
            date.fromisoformat(row["target_date"]) if row["target_date"] else None
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class ProjectRepo:
    """Pure data access for `project` rows. No business logic."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(self, data: ProjectCreate) -> Project:
        now = _now()
        pid = str(uuid.uuid4())
        try:
            await self._conn.execute(
                f"""
                INSERT INTO project ({_COLUMNS}, name_lower)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    data.name,
                    data.description,
                    data.status.value,
                    data.priority,
                    json.dumps(data.calendar_keywords),
                    json.dumps(data.goals),
                    data.target_date.isoformat() if data.target_date else None,
                    now.isoformat(),
                    now.isoformat(),
                    data.name.lower(),
                ),
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise ConflictError(f"project name already exists: {data.name!r}") from exc
        return await self.get(pid)

    async def get(self, project_id: str) -> Project:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM project WHERE id = ?", (project_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("project", project_id)
        return _row_to_project(row)

    async def list(
        self, statuses: Iterable[ProjectStatus] | None = None
    ) -> list[Project]:
        statuses = list(statuses) if statuses is not None else [ProjectStatus.ACTIVE]
        placeholders = ", ".join("?" * len(statuses))
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM project "
            f"WHERE status IN ({placeholders}) "
            "ORDER BY priority ASC, name_lower ASC",
            tuple(s.value for s in statuses),
        )
        return [_row_to_project(r) for r in await cur.fetchall()]

    async def update(self, project_id: str, patch: ProjectUpdate) -> Project:
        existing = await self.get(project_id)
        updates: dict[str, Any] = patch.model_dump(exclude_unset=True)
        if not updates:
            return existing

        sets: list[str] = []
        params: list[object] = []
        for key, value in updates.items():
            if key == "name":
                sets += ["name = ?", "name_lower = ?"]
                params += [value, value.lower()]
            elif key in ("calendar_keywords", "goals"):
                sets.append(f"{key} = ?")
                params.append(json.dumps(value))
            elif key == "status":
                sets.append("status = ?")
                params.append(value.value if isinstance(value, ProjectStatus) else value)
            elif key == "target_date":
                sets.append("target_date = ?")
                params.append(value.isoformat() if value else None)
            else:
                sets.append(f"{key} = ?")
                params.append(value)

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(project_id)

        try:
            await self._conn.execute(
                f"UPDATE project SET {', '.join(sets)} WHERE id = ?", params
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("project name conflict on update") from exc
        return await self.get(project_id)

    async def delete(self, project_id: str) -> None:
        cur = await self._conn.execute(
            "DELETE FROM project WHERE id = ?", (project_id,)
        )
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("project", project_id)
