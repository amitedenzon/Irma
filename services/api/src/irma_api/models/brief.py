"""Brief — the horizon-aware synthesis output Claude must produce."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Horizon = Literal["day", "week", "month", "all"]


class FocusKind(StrEnum):
    TASK = "task"
    EVENT = "event"


class FocusItem(BaseModel):
    """A single actionable row in the brief: a task to do or an event to attend."""

    model_config = ConfigDict(populate_by_name=True)

    kind: FocusKind
    title: str
    project_id: str | None = None
    project_name: str | None = None
    # Populated when kind == TASK.
    task_id: str | None = None
    due_date: str | None = None
    scheduled_for: str | None = None
    # Populated when kind == EVENT (ISO-8601 string; Claude returns a string).
    when: str | None = None
    note: str = ""


class ProjectStatusItem(BaseModel):
    """Per-project rollup row, salient for week/month/overview briefs."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str
    project_name: str
    open_tasks: int = 0
    done_tasks: int = 0
    days_to_target: int | None = None
    note: str = ""


class Brief(BaseModel):
    """A horizon-aware brief in Irma's voice."""

    model_config = ConfigDict(frozen=False, populate_by_name=True)

    horizon: Horizon
    generated_at: datetime
    focus: list[FocusItem] = Field(default_factory=list)
    project_status: list[ProjectStatusItem] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    recommendation: str
    narrative: str

    @property
    def has_attention_signal(self) -> bool:
        """True when the sprite should flip to `alert`."""
        return bool(self.conflicts)
