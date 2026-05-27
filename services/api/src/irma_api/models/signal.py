"""Normalized observer output. The whole pipeline speaks `Signal`."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SignalSource = Literal["calendar", "codebase"]


class Signal(BaseModel):
    """A single observed fact emitted by an Observer.

    The shape is intentionally narrow: every observer normalizes into this
    schema so LeadAgent's synthesis prompt has a uniform input grammar.
    """

    model_config = ConfigDict(frozen=False, populate_by_name=True)

    source: SignalSource
    kind: str
    title: str
    detail: str = ""
    ts: datetime
    meta: dict[str, Any] = Field(default_factory=dict)

    def hash_key(self) -> str:
        """Stable identity for dedupe + brief-cache invalidation.

        Includes everything that semantically distinguishes one observation
        from another. The meta dict is canonicalized (sorted JSON) so the
        hash is order-independent.
        """
        meta_canonical = json.dumps(self.meta, sort_keys=True, default=str)
        payload = "|".join(
            [
                self.source,
                self.kind,
                self.title,
                self.ts.isoformat(),
                meta_canonical,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ScheduleItem(BaseModel):
    """A salient calendar item surfaced in a `StandupBrief`."""

    model_config = ConfigDict(frozen=False)

    ts: datetime
    title: str
    epic: str | None = None
