"""Project Pydantic shape: validators, normalization, DTOs."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from irma_api.models.project import (
    Project,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
)


def _now() -> datetime:
    return datetime(2026, 5, 27, 12, 0, 0)


def test_minimal_project_round_trips() -> None:
    p = Project(
        id="p1",
        name="Thesis",
        created_at=_now(),
        updated_at=_now(),
    )
    assert p.status is ProjectStatus.ACTIVE
    assert p.priority == 2
    assert p.calendar_keywords == []
    assert p.goals == []
    assert p.target_date is None


def test_name_is_trimmed_and_length_bounded() -> None:
    p = Project(id="p1", name="  Thesis  ", created_at=_now(), updated_at=_now())
    assert p.name == "Thesis"

    with pytest.raises(ValidationError):
        Project(id="p1", name="", created_at=_now(), updated_at=_now())

    with pytest.raises(ValidationError):
        Project(id="p1", name="x" * 81, created_at=_now(), updated_at=_now())


def test_priority_must_be_in_range() -> None:
    Project(id="p1", name="x", priority=1, created_at=_now(), updated_at=_now())
    Project(id="p1", name="x", priority=3, created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Project(id="p1", name="x", priority=0, created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Project(id="p1", name="x", priority=4, created_at=_now(), updated_at=_now())


def test_calendar_keywords_lowercased_and_deduped() -> None:
    p = Project(
        id="p1",
        name="x",
        calendar_keywords=["Gal", "gal", "  Lab  ", "lab", "ok"],
        created_at=_now(),
        updated_at=_now(),
    )
    assert p.calendar_keywords == ["gal", "lab", "ok"]


def test_calendar_keywords_min_length_enforced() -> None:
    with pytest.raises(ValidationError):
        Project(
            id="p1",
            name="x",
            calendar_keywords=["a"],
            created_at=_now(),
            updated_at=_now(),
        )


def test_project_create_defaults() -> None:
    pc = ProjectCreate(name="Thesis")
    assert pc.status is ProjectStatus.ACTIVE
    assert pc.priority == 2
    assert pc.calendar_keywords == []
    assert pc.goals == []
    assert pc.target_date is None
    assert pc.description == ""


def test_project_update_all_fields_optional() -> None:
    pu = ProjectUpdate()
    assert pu.model_dump(exclude_unset=True) == {}

    pu2 = ProjectUpdate(name="New", target_date=date(2026, 7, 15))
    assert pu2.model_dump(exclude_unset=True) == {
        "name": "New",
        "target_date": date(2026, 7, 15),
    }


def test_status_enum_values_match_spec() -> None:
    assert ProjectStatus.ACTIVE.value == "active"
    assert ProjectStatus.PAUSED.value == "paused"
    assert ProjectStatus.ARCHIVED.value == "archived"
