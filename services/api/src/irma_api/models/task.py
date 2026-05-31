"""Task entity — a manually entered work item scoped to a Project."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    BLOCKED = "blocked"


class _TaskFields(BaseModel):
    """Shared field definitions for Task + TaskCreate."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    project_id: str
    title: str = Field(min_length=1, max_length=200)
    notes: str = ""
    status: TaskStatus = TaskStatus.TODO
    due_date: date | None = None
    scheduled_for: date | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class Task(_TaskFields):
    """A persisted Task row."""

    id: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    reminder_uuid: str | None = None


class TaskCreate(_TaskFields):
    """Incoming payload for `POST /tasks`."""


class TaskUpdate(BaseModel):
    """Partial update for `PATCH /tasks/{id}`. Every field optional."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    scheduled_for: date | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


def apply_status_transition(task: Task, *, new_status: TaskStatus, now: datetime) -> Task:
    """Return a copy of `task` with `status` updated and `completed_at`
    auto-stamped (set on transition to DONE, cleared on transition out of
    DONE, preserved on DONE→DONE).
    """
    if task.status is new_status:
        return task.model_copy(update={"status": new_status})

    if new_status is TaskStatus.DONE:
        return task.model_copy(update={"status": new_status, "completed_at": now})

    if task.status is TaskStatus.DONE:
        return task.model_copy(update={"status": new_status, "completed_at": None})

    return task.model_copy(update={"status": new_status})
