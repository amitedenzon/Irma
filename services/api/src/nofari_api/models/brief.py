"""Synthesis output. The shape Claude is required to produce."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from nofari_api.models.signal import ScheduleItem


class StandupBrief(BaseModel):
    """Daily PMO brief in Nofari's voice."""

    model_config = ConfigDict(frozen=False)

    generated_at: datetime
    velocity: str
    blockers: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    schedule: list[ScheduleItem] = Field(default_factory=list)
    recommendation: str
    narrative: str

    @property
    def has_attention_signal(self) -> bool:
        """True when the sprite should flip to `alert`."""
        return bool(self.blockers) or bool(self.conflicts)
