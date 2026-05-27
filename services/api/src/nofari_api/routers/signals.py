"""Signals + refresh endpoints.

`POST /refresh` drives the full observe → (optionally synthesize) cycle and
broadcasts AgentState transitions. The same coroutine is wired into
APScheduler for periodic re-observation.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Request

from nofari_api.agents.base import LeadAgentProtocol, Observer
from nofari_api.models.signal import Signal
from nofari_api.runtime.state import AgentState, StateBus
from nofari_api.store.sqlite import SignalStore

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["signals"])


async def gather_signals(observers: list[Observer]) -> list[Signal]:
    results = await asyncio.gather(
        *(o.collect() for o in observers), return_exceptions=True
    )
    out: list[Signal] = []
    for observer, result in zip(observers, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "refresh.observer_failed",
                observer=getattr(observer, "name", "?"),
                error=str(result),
            )
            continue
        out.extend(result)
    return out


async def run_refresh(
    *,
    store: SignalStore,
    observers: list[Observer],
    bus: StateBus,
    lead_agent: LeadAgentProtocol | None = None,
) -> dict[str, int]:
    """Observe → upsert → (Phase 3: synthesize) → publish terminal state."""
    await bus.publish(AgentState.OBSERVING)
    signals = await gather_signals(observers)
    inserted = await store.upsert_signals(signals)
    await store.invalidate_briefs()

    terminal: AgentState = AgentState.IDLE
    if lead_agent is not None:
        await bus.publish(AgentState.THINKING)
        try:
            latest = await store.latest_signals()
            brief = await lead_agent.synthesize(latest)
            terminal = AgentState.ALERT if brief.has_attention_signal else AgentState.IDLE
        except Exception as exc:  # pragma: no cover - protective fallback
            logger.warning("refresh.synth_failed", error=str(exc))
            terminal = AgentState.IDLE

    await bus.publish(terminal)
    return {"observed": len(signals), "inserted": inserted}


@router.get("/signals")
async def list_signals(request: Request) -> list[Signal]:
    store: SignalStore = request.app.state.store
    return await store.latest_signals()


@router.post("/refresh")
async def force_refresh(request: Request) -> dict[str, int]:
    app_state = request.app.state
    return await run_refresh(
        store=app_state.store,
        observers=app_state.observers,
        bus=app_state.bus,
        lead_agent=getattr(app_state, "lead_agent", None),
    )
