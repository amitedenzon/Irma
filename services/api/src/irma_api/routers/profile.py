"""HTTP surface for GET/PATCH /profile (singleton owner configuration)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request

from irma_api.models.profile import Profile, ProfileUpdate
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.runtime.scheduler import Scheduler
from irma_api.store.repos.profile_repo import ProfileRepo
from irma_api.store.sqlite import SignalStore

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

_SCHEDULE_FIELDS = frozenset({"brief_hour", "timezone", "daily_brief_enabled"})


def _repo(request: Request) -> ProfileRepo:
    store: SignalStore = request.app.state.store
    return ProfileRepo(store.connection)


@router.get("", response_model=Profile)
async def get_profile(request: Request) -> Profile:
    """Return the cached profile — no DB hit."""
    cache: ProfileCache = request.app.state.profile_cache
    return cache.current


@router.patch("", response_model=Profile)
async def update_profile(request: Request, body: ProfileUpdate) -> Profile:
    """Partially update the profile, sync the cache, and return the updated row."""
    updated = await _repo(request).update(body)
    cache: ProfileCache = request.app.state.profile_cache
    cache.set(updated)

    # Hot-reschedule the daily-brief job when scheduling-relevant fields changed.
    # Wrapped in try/except: reschedule is a side-effect — if APScheduler raises,
    # the DB write has already committed and the caller gets the updated profile.
    # Diverging scheduler state is logged and will self-heal on next restart.
    if body.model_fields_set & _SCHEDULE_FIELDS:
        scheduler: Scheduler | None = getattr(request.app.state, "scheduler", None)
        if scheduler is not None:
            try:
                scheduler.reschedule_daily_job(
                    hour=updated.brief_hour,
                    timezone=updated.timezone,
                    enabled=updated.daily_brief_enabled,
                )
            except Exception:
                logger.exception(
                    "profile.reschedule_failed",
                    brief_hour=updated.brief_hour,
                    timezone=updated.timezone,
                    enabled=updated.daily_brief_enabled,
                )

    return updated
