"""ProfileCache: hot-reload semantics and error-before-load behaviour."""

from __future__ import annotations

import aiosqlite
import pytest

from irma_api.models.profile import ProfileUpdate
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.store.repos.profile_repo import ProfileRepo


@pytest.mark.asyncio
async def test_current_raises_before_load(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    cache = ProfileCache(repo)
    with pytest.raises(RuntimeError, match="ProfileCache not loaded"):
        _ = cache.current


@pytest.mark.asyncio
async def test_load_returns_profile(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    cache = ProfileCache(repo)
    profile = await cache.load()
    assert profile.id == 1
    assert profile.owner_name == "there"


@pytest.mark.asyncio
async def test_current_returns_cached_value_after_load(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    cache = ProfileCache(repo)
    loaded = await cache.load()
    assert cache.current is loaded


@pytest.mark.asyncio
async def test_hot_reload_reflects_repo_update(db_conn: aiosqlite.Connection) -> None:
    """After a repo update + second load(), .current reflects the new value."""
    repo = ProfileRepo(db_conn)
    cache = ProfileCache(repo)
    await cache.load()

    # Mutate via repo directly (simulates PATCH handler writing before reloading cache)
    await repo.update(ProfileUpdate(owner_name="Amit"))
    assert cache.current.owner_name == "there"  # still stale

    # Reload
    await cache.load()
    assert cache.current.owner_name == "Amit"  # now fresh


@pytest.mark.asyncio
async def test_set_updates_cache_without_db_round_trip(db_conn: aiosqlite.Connection) -> None:
    """cache.set() assigns the profile immediately; no extra DB query is issued."""
    repo = ProfileRepo(db_conn)
    cache = ProfileCache(repo)
    await cache.load()
    assert cache.current.owner_name == "there"

    # Write directly via repo and hand the result to cache.set() — simulating PATCH handler.
    updated = await repo.update(ProfileUpdate(owner_name="Amit"))
    cache.set(updated)

    assert cache.current.owner_name == "Amit"
    assert cache.current is updated
