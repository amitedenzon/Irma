"""Signals + refresh endpoints.

`POST /refresh` runs the observe → upsert cycle and invalidates the
brief cache. Synthesis is lazy: the next GET /brief/<horizon> picks up
the changes.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Request

from irma_api.agents.base import Observer
from irma_api.models.signal import Signal
from irma_api.runtime.state import AgentState, StateBus
from irma_api.store.repos.brief_cache_repo import BriefCacheRepo
from irma_api.store.sqlite import SignalStore

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
) -> dict[str, int]:
    """Observe → upsert → invalidate brief cache → publish terminal state."""
    await bus.publish(AgentState.OBSERVING)
    signals = await gather_signals(observers)
    inserted = await store.upsert_signals(signals)
    await BriefCacheRepo(store.connection).clear()
    await bus.publish(AgentState.IDLE)
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
    )
