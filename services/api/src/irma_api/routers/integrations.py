"""Integration status endpoints for the dashboard."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from irma_api.agents.llm import LLMClient
from irma_api.config import Settings

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationsStatus(BaseModel):
    calendar_linked: bool
    resend_linked: bool
    reminders_linked: bool
    reminders_last_sync_at: datetime | None
    reminders_last_sync_error: str | None
    user_email: str | None
    llm_backend: str | None
    llm_model: str | None


@router.get("/google/status", response_model=IntegrationsStatus)
async def integrations_status(request: Request) -> IntegrationsStatus:
    settings: Settings = request.app.state.settings
    llm: LLMClient | None = getattr(request.app.state, "llm", None)
    sync_svc = getattr(request.app.state, "reminder_sync", None)

    calendar_linked = settings.google_oauth_refresh_token is not None
    resend_linked = (
        settings.resend_api_key is not None
        and settings.irma_user_email is not None
    )
    reminders_linked = settings.reminders_linked and sync_svc is not None

    return IntegrationsStatus(
        calendar_linked=calendar_linked,
        resend_linked=resend_linked,
        reminders_linked=reminders_linked,
        reminders_last_sync_at=getattr(sync_svc, "last_sync_at", None),
        reminders_last_sync_error=getattr(sync_svc, "last_error", None),
        user_email=settings.irma_user_email,
        llm_backend=llm.backend if llm else None,
        llm_model=llm.model if llm else None,
    )


def _trigger_reminder_sync(request: Request) -> None:
    """Fire-and-forget reminders sync after a write to projects/tasks."""
    svc = getattr(request.app.state, "reminder_sync", None)
    if svc is not None:
        import asyncio as _asyncio
        _asyncio.create_task(svc.sync_once())
