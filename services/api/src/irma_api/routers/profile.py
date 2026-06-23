"""HTTP surface for GET/PATCH /profile (singleton owner configuration)."""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Request

from irma_api.models.profile import Profile, ProfileUpdate
from irma_api.runtime.brief_queue import ScheduledBriefQueue
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.store.repos.profile_repo import ProfileRepo
from irma_api.store.sqlite import SignalStore

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

_SCHEDULE_FIELDS = frozenset({"brief_hour", "brief_minute", "timezone", "daily_brief_enabled"})


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

    if body.model_fields_set & _SCHEDULE_FIELDS:
        brief_queue: ScheduledBriefQueue | None = getattr(
            request.app.state, "brief_queue", None
        )
        if brief_queue is not None:
            async def _requeue() -> None:
                try:
                    await brief_queue.ensure_queued()
                except Exception:
                    logger.exception("profile.requeue_failed")

            asyncio.create_task(_requeue())  # noqa: RUF006 — fire-and-forget

    return updated
