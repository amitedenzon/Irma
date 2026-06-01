"""Integration status and connect endpoints for the dashboard."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from irma_api.agents.llm import LLMClient
from irma_api.config import Settings, secret_value_or_none
from irma_api.runtime.profile_cache import current_profile

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationsStatus(BaseModel):
    calendar_linked: bool
    calendar_creds_set: bool
    resend_linked: bool
    reminders_linked: bool
    reminders_last_sync_at: datetime | None
    reminders_last_sync_error: str | None
    user_email: str | None
    setup_complete: bool
    llm_backend: str | None
    llm_model: str | None


def _build_status(request: Request) -> IntegrationsStatus:
    settings: Settings = request.app.state.settings
    llm: LLMClient | None = getattr(request.app.state, "llm", None)
    sync_svc = getattr(request.app.state, "reminder_sync", None)

    profile = current_profile(request.app.state)
    # owner_email from profile takes precedence over the legacy settings field.
    owner_email: str | None = profile.owner_email or settings.irma_user_email

    calendar_linked = (
        secret_value_or_none(settings.google_oauth_refresh_token) is not None
    )
    calendar_creds_set = (
        secret_value_or_none(settings.google_oauth_client_id) is not None
        and secret_value_or_none(settings.google_oauth_client_secret) is not None
    )
    resend_linked = (
        secret_value_or_none(settings.resend_api_key) is not None
        and bool(owner_email)
    )
    reminders_linked = settings.reminders_linked and sync_svc is not None

    return IntegrationsStatus(
        calendar_linked=calendar_linked,
        calendar_creds_set=calendar_creds_set,
        resend_linked=resend_linked,
        reminders_linked=reminders_linked,
        reminders_last_sync_at=getattr(sync_svc, "last_sync_at", None),
        reminders_last_sync_error=getattr(sync_svc, "last_error", None),
        user_email=owner_email,
        setup_complete=profile.setup_complete,
        llm_backend=llm.backend if llm else None,
        llm_model=llm.model if llm else None,
    )


@router.get("/google/status", response_model=IntegrationsStatus)
async def integrations_status(request: Request) -> IntegrationsStatus:
    return _build_status(request)


@router.post("/google/connect", response_model=IntegrationsStatus)
async def connect_google_calendar(request: Request) -> IntegrationsStatus:
    """Trigger the installed-app OAuth flow and persist the refresh token to .env."""
    settings: Settings = request.app.state.settings
    client_id = secret_value_or_none(settings.google_oauth_client_id)
    client_secret = secret_value_or_none(settings.google_oauth_client_secret)

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=422,
            detail=(
                "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET must be "
                "set in Settings before connecting."
            ),
        )

    from irma_api.auth.google_oauth import OAuthCancelled, run_installed_app_flow
    from irma_api.routers.settings import _read_env, _write_env

    try:
        result = await run_installed_app_flow(
            client_id=client_id, client_secret=client_secret
        )
    except OAuthCancelled as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    env = _read_env()
    env["GOOGLE_OAUTH_REFRESH_TOKEN"] = result.refresh_token
    _write_env(env)

    return _build_status(request)


def _trigger_reminder_sync(request: Request) -> None:
    """Fire-and-forget reminders sync after a write to projects/tasks."""
    svc = getattr(request.app.state, "reminder_sync", None)
    if svc is not None:
        import asyncio as _asyncio
        _asyncio.create_task(svc.sync_once())
