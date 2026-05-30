"""Models for the emailed daily brief.

The factual sections (`progress`, `today_focus`, `lookahead_tasks`,
`calendar_text`) are computed deterministically in Python. Only `narrative`,
`recommendation`, and `conflicts` come from the LLM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from irma_api.models.brief import FocusItem


class ProjectProgress(BaseModel):
    project_id: str
    project_name: str
    completed_since: int = 0
    added_since: int = 0
    open_now: int = 0
    done_now: int = 0
    note: str = ""


class LookaheadItem(BaseModel):
    title: str
    when: str  # ISO date
    kind: Literal["due", "scheduled"]
    project_name: str | None = None


class DailyBrief(BaseModel):
    generated_at: datetime
    narrative: str = ""
    recommendation: str = ""
    conflicts: list[str] = Field(default_factory=list)
    progress: list[ProjectProgress] = Field(default_factory=list)
    today_focus: list[FocusItem] = Field(default_factory=list)
    lookahead_tasks: list[LookaheadItem] = Field(default_factory=list)
    calendar_text: str | None = None
    has_baseline: bool = False
