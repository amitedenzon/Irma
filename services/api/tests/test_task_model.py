"""Task Pydantic shape: validators, status transitions, DTOs."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from irma_api.models.task import (
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    apply_status_transition,
)


def _now() -> datetime:
    return datetime(2026, 5, 27, 12, 0, 0)


def test_minimal_task_round_trips() -> None:
    t = Task(
        id="t1",
        project_id="p1",
        title="Draft results",
        created_at=_now(),
        updated_at=_now(),
    )
    assert t.status is TaskStatus.TODO
    assert t.notes == ""
    assert t.due_date is None
    assert t.scheduled_for is None
    assert t.estimated_minutes is None
    assert t.completed_at is None


def test_title_length_bounds() -> None:
    Task(id="t1", project_id="p1", title="x", created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Task(id="t1", project_id="p1", title="", created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Task(
            id="t1",
            project_id="p1",
            title="x" * 201,
            created_at=_now(),
            updated_at=_now(),
        )


def test_estimated_minutes_must_be_positive() -> None:
    Task(
        id="t1",
        project_id="p1",
        title="x",
        estimated_minutes=1,
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(ValidationError):
        Task(
            id="t1",
            project_id="p1",
            title="x",
            estimated_minutes=0,
            created_at=_now(),
            updated_at=_now(),
        )


def test_due_date_in_past_is_allowed() -> None:
    Task(
        id="t1",
        project_id="p1",
        title="x",
        due_date=date(1999, 1, 1),
        created_at=_now(),
        updated_at=_now(),
    )


def test_apply_status_transition_done_stamps_completed_at() -> None:
    existing = Task(
        id="t1",
        project_id="p1",
        title="x",
        status=TaskStatus.TODO,
        created_at=_now(),
        updated_at=_now(),
    )
    new = apply_status_transition(
        existing,
        new_status=TaskStatus.DONE,
        now=datetime(2026, 6, 1, 10, 0),
    )
    assert new.status is TaskStatus.DONE
    assert new.completed_at == datetime(2026, 6, 1, 10, 0)
    assert existing.completed_at is None


def test_apply_status_transition_unsetting_done_clears_completed_at() -> None:
    existing = Task(
        id="t1",
        project_id="p1",
        title="x",
        status=TaskStatus.DONE,
        completed_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    new = apply_status_transition(existing, new_status=TaskStatus.DOING, now=datetime(2026, 6, 1))
    assert new.status is TaskStatus.DOING
    assert new.completed_at is None


def test_apply_status_transition_done_to_done_preserves_completed_at() -> None:
    first = datetime(2026, 5, 1, 9, 0)
    existing = Task(
        id="t1",
        project_id="p1",
        title="x",
        status=TaskStatus.DONE,
        completed_at=first,
        created_at=_now(),
        updated_at=_now(),
    )
    new = apply_status_transition(existing, new_status=TaskStatus.DONE, now=datetime(2026, 6, 1))
    assert new.completed_at == first


def test_task_create_defaults() -> None:
    tc = TaskCreate(project_id="p1", title="x")
    assert tc.status is TaskStatus.TODO
    assert tc.due_date is None


def test_task_update_all_fields_optional() -> None:
    tu = TaskUpdate()
    assert tu.model_dump(exclude_unset=True) == {}
    tu2 = TaskUpdate(status=TaskStatus.DOING)
    assert tu2.model_dump(exclude_unset=True) == {"status": TaskStatus.DOING}


def test_status_enum_values_match_spec() -> None:
    assert TaskStatus.TODO.value == "todo"
    assert TaskStatus.DOING.value == "doing"
    assert TaskStatus.DONE.value == "done"
    assert TaskStatus.BLOCKED.value == "blocked"
