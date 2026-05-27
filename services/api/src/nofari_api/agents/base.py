"""Observer + LeadAgent protocols. Anything that satisfies these is plug-compatible."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nofari_api.models.brief import StandupBrief
from nofari_api.models.signal import Signal


@runtime_checkable
class Observer(Protocol):
    """Async, side-effect-free signal collector."""

    name: str

    async def collect(self) -> list[Signal]:  # pragma: no cover - protocol
        ...


class LeadAgentProtocol(Protocol):
    """Structural type for the Phase 3 synthesis agent.

    Defined here (and not in `agents/lead_agent.py`) so Phase 2 code can refer
    to the typed surface without importing a module that doesn't exist yet.
    """

    async def synthesize(
        self, signals: list[Signal]
    ) -> StandupBrief:  # pragma: no cover - protocol
        ...
