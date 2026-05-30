"""Project entity — manually managed unit grouping goals + calendar keywords."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


def _normalize_keywords(raw: list[str]) -> list[str]:
    """Lowercase, trim, dedupe (preserve first-seen order), enforce min len."""
    seen: dict[str, None] = {}
    for kw in raw:
        if not isinstance(kw, str):
            raise ValueError("calendar_keywords entries must be strings")
        normalized = kw.strip().lower()
        if len(normalized) < 2:
            raise ValueError(f"calendar keyword too short: {kw!r}")
        seen.setdefault(normalized, None)
    return list(seen.keys())


class _ProjectFields(BaseModel):
    """Shared field definitions for Project + ProjectCreate + ProjectUpdate."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    priority: int = Field(default=2, ge=1, le=3)
    calendar_keywords: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    target_date: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("calendar_keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("calendar_keywords must be a list")
        return _normalize_keywords(v)


class Project(_ProjectFields):
    """A persisted Project row."""

    id: str
    created_at: datetime
    updated_at: datetime
    reminder_calendar_id: str | None = None


class ProjectCreate(_ProjectFields):
    """Incoming payload for `POST /projects`."""


class ProjectUpdate(BaseModel):
    """Partial update for `PATCH /projects/{id}`. Every field optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    status: ProjectStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    calendar_keywords: list[str] | None = None
    goals: list[str] | None = None
    target_date: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("calendar_keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, v: object) -> object:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("calendar_keywords must be a list")
        return _normalize_keywords(v)
