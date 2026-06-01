"""Pydantic DTOs mirroring the Swift helper's JSON surface."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HelperReminder(BaseModel):
    """One reminder row as reported by `helper list`."""

    model_config = ConfigDict(populate_by_name=True)

    uuid: str
    title: str
    notes: str = ""
    due_date: date | None = None
    start_date: date | None = None
    is_completed: bool = False
    completion_date: datetime | None = None
    last_modified: datetime


class ReminderFields(BaseModel):
    """Field bag for create/update ops; every field optional."""

    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    notes: str | None = None
    due_date: date | None = None
    start_date: date | None = None
    is_completed: bool | None = None


class CalendarSummary(BaseModel):
    """One calendar entry from `helper list-calendars`."""

    model_config = ConfigDict(populate_by_name=True)

    calendar_id: str
    title: str


class _Create(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Literal["create"] = "create"
    fields: ReminderFields


class _Update(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Literal["update"] = "update"
    uuid: str
    fields: ReminderFields


class _Delete(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    op: Literal["delete"] = "delete"
    uuid: str


class BatchOp(BaseModel):
    """Discriminated wrapper around create / update / delete.

    Use the constructors `create_op`, `update_op`, `delete_op` rather than
    instantiating the underlying union directly.
    """

    model_config = ConfigDict(populate_by_name=True)
    root: _Create | _Update | _Delete = Field(discriminator="op")

    @classmethod
    def create_op(cls, fields: ReminderFields) -> "BatchOp":
        return cls(root=_Create(fields=fields))

    @classmethod
    def update_op(cls, uuid: str, fields: ReminderFields) -> "BatchOp":
        return cls(root=_Update(uuid=uuid, fields=fields))

    @classmethod
    def delete_op(cls, uuid: str) -> "BatchOp":
        return cls(root=_Delete(uuid=uuid))

    def model_dump(self, **kwargs: object) -> dict[str, object]:  # type: ignore[override]
        return self.root.model_dump(**kwargs)


class BatchResult(BaseModel):
    """One result row from `helper batch`."""

    model_config = ConfigDict(populate_by_name=True)

    index: int
    ok: bool
    uuid: str | None = None
    last_modified: datetime | None = None
    error: str | None = None
