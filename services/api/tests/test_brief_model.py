"""Brief Pydantic shape: horizon types, focus item kinds, parsing."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from irma_api.models.brief import (
    Brief,
    FocusItem,
    FocusKind,
    ProjectStatusItem,
)


def _now() -> datetime:
    return datetime(2026, 5, 27, 12, 0, 0)


def test_brief_minimum_required_fields() -> None:
    b = Brief(
        horizon="day",
        generated_at=_now(),
        focus=[],
        project_status=[],
        conflicts=[],
        recommendation="Start with the draft.",
        narrative="",
    )
    assert b.horizon == "day"
    assert b.has_attention_signal is False


def test_horizon_must_be_known_value() -> None:
    Brief(
        horizon="week",
        generated_at=_now(),
        focus=[],
        project_status=[],
        conflicts=[],
        recommendation="ok",
        narrative="",
    )
    with pytest.raises(ValidationError):
        Brief(
            horizon="quarter",
            generated_at=_now(),
            focus=[],
            project_status=[],
            conflicts=[],
            recommendation="ok",
            narrative="",
        )


def test_focus_item_task_kind() -> None:
    fi = FocusItem(
        kind=FocusKind.TASK,
        title="Draft results",
        project_id="p1",
        project_name="Thesis",
        task_id="t1",
        due_date="2026-05-28",
    )
    assert fi.kind is FocusKind.TASK
    assert fi.task_id == "t1"


def test_focus_item_event_kind() -> None:
    fi = FocusItem(
        kind=FocusKind.EVENT,
        title="Meeting with Prof. Gal",
        project_id="p1",
        project_name="Thesis",
        when="2026-05-27T14:00:00Z",
    )
    assert fi.kind is FocusKind.EVENT
    assert fi.task_id is None


def test_has_attention_signal_flips_on_conflicts() -> None:
    b = Brief(
        horizon="day",
        generated_at=_now(),
        focus=[],
        project_status=[],
        conflicts=["MIT block overlaps thesis window"],
        recommendation="ok",
        narrative="",
    )
    assert b.has_attention_signal is True


def test_brief_round_trips_through_json() -> None:
    b = Brief(
        horizon="day",
        generated_at=_now(),
        focus=[
            FocusItem(
                kind=FocusKind.TASK,
                title="x",
                project_id="p1",
                project_name="Thesis",
                task_id="t1",
            ),
        ],
        project_status=[
            ProjectStatusItem(
                project_id="p1",
                project_name="Thesis",
                open_tasks=3,
                done_tasks=1,
                note="on track",
            )
        ],
        conflicts=[],
        recommendation="x",
        narrative="x",
    )
    blob = b.model_dump_json()
    parsed = Brief.model_validate_json(blob)
    assert parsed == b


def test_standup_brief_is_gone() -> None:
    """The old auto-observed brief shape must not be importable anymore."""
    from irma_api.models import brief

    assert not hasattr(brief, "StandupBrief")
