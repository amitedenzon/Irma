"""In-memory hot-reload cache for the singleton Profile row.

Tools and observers call `.current` synchronously at call time; the startup
hook and every PATCH handler call `await cache.load()` to refresh the cached
value from the database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from irma_api.models.profile import Profile
from irma_api.store.repos.profile_repo import ProfileRepo


def current_profile(app_state: Any) -> Profile:
    """Return the cached Profile from *app_state*, or a neutral default.

    A neutral (all-defaults) Profile is returned whenever the
    ``profile_cache`` attribute is absent — typically in tests or during
    early startup before the cache has been loaded.
    """
    cache: ProfileCache | None = getattr(app_state, "profile_cache", None)
    if cache is not None:
        return cache.current
    return Profile(updated_at=datetime.now(UTC))


class ProfileCache:
    """Holds the latest :class:`Profile` in memory for synchronous hot reads."""

    def __init__(self, repo: ProfileRepo) -> None:
        self._repo = repo
        self._profile: Profile | None = None

    async def load(self) -> Profile:
        """Fetch from DB, update the cache, and return the refreshed Profile."""
        self._profile = await self._repo.get()
        return self._profile

    def set(self, profile: Profile) -> None:
        """Assign an already-fetched Profile to the cache without a DB round-trip.

        Used by PATCH handlers that already hold the updated row so the cache
        stays consistent without an extra query.
        """
        self._profile = profile

    @property
    def current(self) -> Profile:
        """Return the cached Profile. Raises if :meth:`load` was never called."""
        if self._profile is None:
            raise RuntimeError("ProfileCache not loaded — call await cache.load() first")
        return self._profile
