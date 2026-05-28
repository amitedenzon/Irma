"""Integration status endpoints for the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from irma_api.agents.llm import LLMClient
from irma_api.config import Settings

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationsStatus(BaseModel):
    calendar_linked: bool
    resend_linked: bool
    user_email: str | None
    llm_backend: str | None
    llm_model: str | None


@router.get("/google/status", response_model=IntegrationsStatus)
async def integrations_status(request: Request) -> IntegrationsStatus:
    settings: Settings = request.app.state.settings
    llm: LLMClient | None = getattr(request.app.state, "llm", None)
    calendar_linked = settings.google_oauth_refresh_token is not None
    resend_linked = (
        settings.resend_api_key is not None
        and settings.irma_user_email is not None
    )
    return IntegrationsStatus(
        calendar_linked=calendar_linked,
        resend_linked=resend_linked,
        user_email=settings.irma_user_email,
        llm_backend=llm.backend if llm else None,
        llm_model=llm.model if llm else None,
    )
