"""Link / unlink / force-sync endpoints for Apple Reminders integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

if TYPE_CHECKING:
    from irma_api.integrations.reminders.bridge import ReminderBridge
    from irma_api.integrations.reminders.sync import ReminderSyncService

router = APIRouter(prefix="/integrations/reminders", tags=["integrations"])


class LinkResponse(BaseModel):
    linked: bool


class SyncResponse(BaseModel):
    created_calendars: int
    renamed_calendars: int
    deleted_calendars: int
    unlinked_projects: int
    renamed_projects: int
    created_remote: int
    patched_remote: int
    deleted_remote: int
    created_local: int
    patched_local: int
    deleted_local: int
    moved_local: int


@router.post("/link", response_model=LinkResponse)
async def link(request: Request) -> LinkResponse:
    bridge: ReminderBridge | None = getattr(request.app.state, "reminder_bridge", None)
    factory = getattr(request.app.state, "reminder_sync_factory", None)
    if bridge is None or factory is None:
        raise HTTPException(
            status_code=503,
            detail="reminders helper not configured (missing binary or settings)",
        )

    granted = await bridge.request_access()
    if not granted:
        raise HTTPException(status_code=403, detail="reminders access denied")

    request.app.state.settings.reminders_linked = True
    svc = factory()
    request.app.state.reminder_sync = svc
    await svc.sync_once()
    return LinkResponse(linked=True)


@router.delete("/link", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(request: Request) -> Response:
    """Clear linkage. Does not delete the macOS Reminders lists themselves."""
    store = request.app.state.store
    conn = store.connection
    await conn.execute("UPDATE task SET reminder_uuid = NULL")
    await conn.execute("UPDATE project SET reminder_calendar_id = NULL")
    await conn.commit()
    request.app.state.settings.reminders_linked = False
    request.app.state.reminder_sync = None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sync", response_model=SyncResponse)
async def sync_now(request: Request) -> SyncResponse:
    svc: ReminderSyncService | None = getattr(request.app.state, "reminder_sync", None)
    if svc is None:
        raise HTTPException(status_code=409, detail="reminders integration not linked")
    stats = await svc.sync_once()
    return SyncResponse(**{k: getattr(stats, k) for k in SyncResponse.model_fields})
