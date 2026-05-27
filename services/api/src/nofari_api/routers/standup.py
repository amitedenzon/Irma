"""Standup brief endpoint — populated in Phase 3."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from nofari_api.agents.base import LeadAgentProtocol
from nofari_api.models.brief import StandupBrief
from nofari_api.runtime.state import AgentState, StateBus
from nofari_api.store.sqlite import SignalStore

router = APIRouter(tags=["standup"])


@router.get("/standup", response_model=StandupBrief)
async def get_standup(request: Request) -> StandupBrief:
    lead_agent: LeadAgentProtocol | None = getattr(
        request.app.state, "lead_agent", None
    )
    if lead_agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LeadAgent not configured (Phase 3 not active)",
            headers={"Retry-After": "30"},
        )

    store: SignalStore = request.app.state.store
    signals = await store.latest_signals()
    if not signals:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no signals yet — POST /api/v1/refresh first",
            headers={"Retry-After": "5"},
        )

    bus: StateBus = request.app.state.bus
    await bus.publish(AgentState.THINKING)
    brief = await lead_agent.synthesize(signals)
    await bus.publish(
        AgentState.ALERT if brief.has_attention_signal else AgentState.IDLE
    )
    return brief
