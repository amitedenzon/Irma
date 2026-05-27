"""Observer + LeadAgent protocols. Anything that satisfies these is plug-compatible."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from irma_api.models.brief import Brief, Horizon
from irma_api.models.signal import Signal


@runtime_checkable
class Observer(Protocol):
    """Async, side-effect-free signal collector."""

    name: str

    async def collect(self) -> list[Signal]:  # pragma: no cover - protocol
        ...


class LeadAgentProtocol(Protocol):
    """Structural type for the horizon-aware synthesis agent."""

    async def synthesize(self, horizon: Horizon) -> Brief:  # pragma: no cover - protocol
        ...
