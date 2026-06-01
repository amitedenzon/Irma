"""Profile Pydantic shape: validators, defaults, ProfileUpdate semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from irma_api.models.profile import Profile, ProfileUpdate


def _now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Profile read model
# ---------------------------------------------------------------------------


def test_profile_defaults() -> None:
    p = Profile(updated_at=_now())
    assert p.id == 1
    assert p.owner_name == "there"
    assert p.owner_role == ""
    assert p.owner_email is None
    assert p.timezone == "UTC"
    assert p.persona_blurb == ""
    assert p.calendar_exclude_ids == []
    assert p.daily_brief_enabled is True
    assert p.brief_hour == 8
    assert p.brief_lookahead_days == 3
    assert p.setup_complete is False


def test_brief_hour_bounds() -> None:
    Profile(brief_hour=0, updated_at=_now())
    Profile(brief_hour=23, updated_at=_now())
    with pytest.raises(ValidationError):
        Profile(brief_hour=-1, updated_at=_now())
    with pytest.raises(ValidationError):
        Profile(brief_hour=24, updated_at=_now())


def test_brief_lookahead_days_bounds() -> None:
    Profile(brief_lookahead_days=1, updated_at=_now())
    Profile(brief_lookahead_days=14, updated_at=_now())
    with pytest.raises(ValidationError):
        Profile(brief_lookahead_days=0, updated_at=_now())
    with pytest.raises(ValidationError):
        Profile(brief_lookahead_days=15, updated_at=_now())


# ---------------------------------------------------------------------------
# ProfileUpdate validators
# ---------------------------------------------------------------------------


def test_profile_update_all_fields_optional() -> None:
    pu = ProfileUpdate()
    assert pu.model_dump(exclude_unset=True) == {}


def test_profile_update_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        ProfileUpdate(nonexistent_field="x")  # type: ignore[call-arg]


def test_owner_name_trimmed() -> None:
    pu = ProfileUpdate(owner_name="  Amit  ")
    assert pu.owner_name == "Amit"


def test_owner_role_trimmed() -> None:
    pu = ProfileUpdate(owner_role="  AI Researcher  ")
    assert pu.owner_role == "AI Researcher"


def test_persona_blurb_trimmed() -> None:
    pu = ProfileUpdate(persona_blurb="  calm dog  ")
    assert pu.persona_blurb == "calm dog"


def test_timezone_valid_iana_accepted() -> None:
    pu = ProfileUpdate(timezone="America/New_York")
    assert pu.timezone == "America/New_York"

    pu2 = ProfileUpdate(timezone="Asia/Tokyo")
    assert pu2.timezone == "Asia/Tokyo"

    pu3 = ProfileUpdate(timezone="UTC")
    assert pu3.timezone == "UTC"


def test_timezone_invalid_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid IANA timezone"):
        ProfileUpdate(timezone="Not/AZone")

    with pytest.raises(ValidationError, match="invalid IANA timezone"):
        ProfileUpdate(timezone="Europe/Fake")


def test_brief_hour_bounds_in_update() -> None:
    ProfileUpdate(brief_hour=0)
    ProfileUpdate(brief_hour=23)
    with pytest.raises(ValidationError):
        ProfileUpdate(brief_hour=-1)
    with pytest.raises(ValidationError):
        ProfileUpdate(brief_hour=24)


def test_brief_lookahead_days_bounds_in_update() -> None:
    ProfileUpdate(brief_lookahead_days=1)
    ProfileUpdate(brief_lookahead_days=14)
    with pytest.raises(ValidationError):
        ProfileUpdate(brief_lookahead_days=0)
    with pytest.raises(ValidationError):
        ProfileUpdate(brief_lookahead_days=15)


def test_timezone_none_passes_in_update() -> None:
    """Explicit None is the 'not-set' sentinel; should not raise."""
    pu = ProfileUpdate(timezone=None)
    assert pu.timezone is None
