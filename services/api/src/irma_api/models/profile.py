"""Profile entity — single-row owner configuration for the Irma assistant."""

from __future__ import annotations

import zoneinfo
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Profile(BaseModel):
    """A single persisted Profile row (id is always 1)."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    id: int = 1
    owner_name: str = "there"
    owner_role: str = ""
    owner_email: str | None = None
    timezone: str = "UTC"
    persona_blurb: str = ""
    calendar_exclude_ids: list[str] = Field(default_factory=list)
    daily_brief_enabled: bool = True
    brief_hour: int = Field(default=8, ge=0, le=23)
    brief_lookahead_days: int = Field(default=3, ge=1, le=14)
    setup_complete: bool = False
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Partial update for `PATCH /profile`. Every field optional."""

    model_config = ConfigDict(extra="forbid")

    owner_name: str | None = None
    owner_role: str | None = None
    owner_email: str | None = None
    timezone: str | None = None
    persona_blurb: str | None = None
    calendar_exclude_ids: list[str] | None = None
    daily_brief_enabled: bool | None = None
    brief_hour: int | None = Field(default=None, ge=0, le=23)
    brief_lookahead_days: int | None = Field(default=None, ge=1, le=14)
    setup_complete: bool | None = None

    @field_validator("owner_name", mode="before")
    @classmethod
    def _trim_owner_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("owner_role", mode="before")
    @classmethod
    def _trim_owner_role(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("persona_blurb", mode="before")
    @classmethod
    def _trim_persona_blurb(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("timezone", mode="before")
    @classmethod
    def _validate_timezone(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("timezone must be a string")
        try:
            zoneinfo.ZoneInfo(v)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError) as exc:
            raise ValueError(f"invalid IANA timezone: {v!r}") from exc
        return v
