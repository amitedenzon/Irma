"""HTTP surface for GET/PATCH /profile (singleton owner configuration)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from irma_api.models.profile import Profile, ProfileUpdate
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.store.repos.profile_repo import ProfileRepo
from irma_api.store.sqlite import SignalStore

router = APIRouter(prefix="/profile", tags=["profile"])


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
    """Partially update the profile, reload the cache, and return the updated row."""
    updated = await _repo(request).update(body)
    await request.app.state.profile_cache.load()
    return updated
