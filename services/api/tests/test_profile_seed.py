"""import_env_defaults: idempotency, field import, no-clobber guarantee."""

from __future__ import annotations

import aiosqlite
import pytest

from irma_api.config import Settings
from irma_api.models.profile import ProfileUpdate
from irma_api.store.profile_seed import import_env_defaults
from irma_api.store.repos.profile_repo import ProfileRepo


def _settings(**overrides: object) -> Settings:
    """Build a minimal Settings with sensible defaults; override as needed."""
    base: dict[str, object] = {
        "irma_user_email": None,
        "irma_brief_timezone": "UTC",
        "irma_brief_hour": 8,
        "irma_calendar_exclude_ids": [],
        "irma_brief_lookahead_days": 3,
        "irma_daily_brief_enabled": True,
        # suppress unrelated required secrets
        "anthropic_api_key": None,
        "google_oauth_client_id": None,
        "google_oauth_client_secret": None,
        "google_oauth_refresh_token": None,
        "resend_api_key": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_import_sets_email_and_marks_setup_complete(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProfileRepo(db_conn)
    settings = _settings(
        irma_user_email="amit@example.com",
        irma_brief_timezone="Asia/Jerusalem",
        irma_brief_hour=7,
        irma_calendar_exclude_ids=["cal-abc"],
        irma_brief_lookahead_days=5,
        irma_daily_brief_enabled=False,
    )
    await import_env_defaults(repo, settings)
    profile = await repo.get()

    assert profile.owner_email == "amit@example.com"
    assert profile.timezone == "Asia/Jerusalem"
    assert profile.brief_hour == 7
    assert profile.calendar_exclude_ids == ["cal-abc"]
    assert profile.brief_lookahead_days == 5
    assert profile.daily_brief_enabled is False
    assert profile.setup_complete is True


@pytest.mark.asyncio
async def test_import_idempotent_when_setup_complete(
    db_conn: aiosqlite.Connection,
) -> None:
    """Running import_env_defaults twice is a no-op after setup_complete=True."""
    repo = ProfileRepo(db_conn)
    settings = _settings(
        irma_user_email="amit@example.com",
        irma_brief_timezone="Asia/Jerusalem",
    )

    await import_env_defaults(repo, settings)
    first = await repo.get()
    assert first.setup_complete is True

    # Second run must not touch the profile at all.
    await import_env_defaults(repo, settings)
    second = await repo.get()
    assert second == first


@pytest.mark.asyncio
async def test_import_does_not_clobber_customised_fields(
    db_conn: aiosqlite.Connection,
) -> None:
    """Fields already customised by the user must not be overwritten."""
    repo = ProfileRepo(db_conn)
    # User has already set a non-default timezone and email.
    await repo.update(
        ProfileUpdate(
            owner_email="custom@example.com",
            timezone="America/New_York",
        )
    )

    settings = _settings(
        irma_user_email="env@example.com",
        irma_brief_timezone="Asia/Jerusalem",
    )
    await import_env_defaults(repo, settings)
    profile = await repo.get()

    # Custom values must not be clobbered — import checks neutral defaults only.
    assert profile.owner_email == "custom@example.com"
    assert profile.timezone == "America/New_York"


@pytest.mark.asyncio
async def test_import_no_email_does_not_set_setup_complete(
    db_conn: aiosqlite.Connection,
) -> None:
    """Without an owner email, setup_complete stays False (wizard still needed)."""
    repo = ProfileRepo(db_conn)
    settings = _settings(irma_user_email=None)
    await import_env_defaults(repo, settings)
    profile = await repo.get()
    assert profile.setup_complete is False
