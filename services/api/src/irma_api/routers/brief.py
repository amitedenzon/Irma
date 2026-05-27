"""HTTP surface for horizon-aware briefs.

The four routes are thin shells that resolve to a single LeadAgent call.
The shell is split out per-horizon so the URLs are self-documenting and
each cache row has a stable, named endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from irma_api.agents.base import LeadAgentProtocol
from irma_api.models.brief import Brief, Horizon

router = APIRouter(prefix="/brief", tags=["brief"])


async def _synthesize(request: Request, horizon: Horizon) -> Brief | JSONResponse:
    """Synthesize on-demand. Does NOT publish to the AgentState bus —
    that would feedback-loop with the dashboard's SSE-triggered reload.
    The dashboard tracks per-request loading in its own UI state."""
    lead_agent: LeadAgentProtocol | None = getattr(request.app.state, "lead_agent", None)
    if lead_agent is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "synthesis_unavailable",
                "detail": "LeadAgent not configured",
            },
            headers={"Retry-After": "30"},
        )
    return await lead_agent.synthesize(horizon)


@router.get("/today", response_model=Brief)
async def brief_today(request: Request) -> Brief | JSONResponse:
    return await _synthesize(request, "day")


@router.get("/week", response_model=Brief)
async def brief_week(request: Request) -> Brief | JSONResponse:
    return await _synthesize(request, "week")


@router.get("/month", response_model=Brief)
async def brief_month(request: Request) -> Brief | JSONResponse:
    return await _synthesize(request, "month")


@router.get("/overview", response_model=Brief)
async def brief_overview(request: Request) -> Brief | JSONResponse:
    return await _synthesize(request, "all")
