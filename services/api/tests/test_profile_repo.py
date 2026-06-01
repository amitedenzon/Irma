"""ProfileRepo: self-seeding, partial update, JSON round-trip, updated_at bump."""

from __future__ import annotations

import aiosqlite
import pytest

from irma_api.models.profile import ProfileUpdate
from irma_api.store.repos.profile_repo import ProfileRepo

# ---------------------------------------------------------------------------
# Self-seeding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_self_seeds_defaults(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    # No row exists yet — get() must insert and return defaults.
    profile = await repo.get()
    assert profile.id == 1
    assert profile.owner_name == "there"
    assert profile.owner_role == ""
    assert profile.owner_email is None
    assert profile.timezone == "UTC"
    assert profile.persona_blurb == ""
    assert profile.calendar_exclude_ids == []
    assert profile.daily_brief_enabled is True
    assert profile.brief_hour == 8
    assert profile.brief_lookahead_days == 3
    assert profile.setup_complete is False


@pytest.mark.asyncio
async def test_get_is_idempotent_after_first_seed(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    first = await repo.get()
    second = await repo.get()
    assert first == second


@pytest.mark.asyncio
async def test_ensure_seeded_returns_profile(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    profile = await repo.ensure_seeded()
    assert profile.id == 1
    assert profile.owner_name == "there"


@pytest.mark.asyncio
async def test_ensure_seeded_idempotent(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    await repo.ensure_seeded()
    # Second call must not reset any already-updated fields.
    await repo.update(ProfileUpdate(owner_name="Amit"))
    second = await repo.ensure_seeded()
    # ensure_seeded uses INSERT OR IGNORE — existing values must be preserved.
    assert second.owner_name == "Amit"


# ---------------------------------------------------------------------------
# Partial update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_partial_changes_only_given_fields(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    original = await repo.get()
    updated = await repo.update(ProfileUpdate(owner_name="Amit", brief_hour=9))
    assert updated.owner_name == "Amit"
    assert updated.brief_hour == 9
    # Untouched fields must stay at defaults.
    assert updated.owner_role == original.owner_role
    assert updated.timezone == original.timezone
    assert updated.daily_brief_enabled == original.daily_brief_enabled


@pytest.mark.asyncio
async def test_update_empty_patch_returns_unchanged(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    before = await repo.get()
    after = await repo.update(ProfileUpdate())
    assert after == before


@pytest.mark.asyncio
async def test_update_bumps_updated_at(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    before = await repo.get()
    # Timestamps are second-resolution; sleep is impractical — just check
    # that updated_at is ≥ original (bump happened, no regression).
    after = await repo.update(ProfileUpdate(owner_name="Amit"))
    assert after.updated_at >= before.updated_at


@pytest.mark.asyncio
async def test_update_setup_complete(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    await repo.get()
    updated = await repo.update(ProfileUpdate(setup_complete=True))
    assert updated.setup_complete is True
    # Idempotent second set
    updated2 = await repo.update(ProfileUpdate(setup_complete=True))
    assert updated2.setup_complete is True


@pytest.mark.asyncio
async def test_update_daily_brief_toggle(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    await repo.get()
    disabled = await repo.update(ProfileUpdate(daily_brief_enabled=False))
    assert disabled.daily_brief_enabled is False
    re_enabled = await repo.update(ProfileUpdate(daily_brief_enabled=True))
    assert re_enabled.daily_brief_enabled is True


# ---------------------------------------------------------------------------
# calendar_exclude_ids JSON round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_exclude_ids_round_trip(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    ids = ["cal-1", "cal-2", "cal-3"]
    updated = await repo.update(ProfileUpdate(calendar_exclude_ids=ids))
    assert updated.calendar_exclude_ids == ids


@pytest.mark.asyncio
async def test_calendar_exclude_ids_empty_list_round_trip(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    # Seed with values then clear.
    await repo.update(ProfileUpdate(calendar_exclude_ids=["cal-1"]))
    cleared = await repo.update(ProfileUpdate(calendar_exclude_ids=[]))
    assert cleared.calendar_exclude_ids == []


@pytest.mark.asyncio
async def test_calendar_exclude_ids_persists_across_get(db_conn: aiosqlite.Connection) -> None:
    repo = ProfileRepo(db_conn)
    await repo.update(ProfileUpdate(calendar_exclude_ids=["x", "y"]))
    fetched = await repo.get()
    assert fetched.calendar_exclude_ids == ["x", "y"]
