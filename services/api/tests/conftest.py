"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    """Clear the @lru_cache around get_settings() between tests."""
    from irma_api.config import get_settings

    get_settings.cache_clear()
