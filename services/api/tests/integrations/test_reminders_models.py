from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from irma_api.integrations.reminders.models import (
    BatchOp,
    BatchResult,
    CalendarSummary,
    HelperReminder,
    ReminderFields,
)


def test_helper_reminder_parses_helper_json() -> None:
    raw = {
        "uuid": "U-1",
        "title": "buy milk",
        "notes": "",
        "due_date": "2026-06-01",
        "start_date": None,
        "is_completed": False,
        "completion_date": None,
        "last_modified": "2026-05-30T10:00:00Z",
    }
    rem = HelperReminder.model_validate(raw)
    assert rem.uuid == "U-1"
    assert rem.due_date == date(2026, 6, 1)
    assert rem.start_date is None
    assert rem.last_modified == datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)


def test_batch_op_create_serialises_with_op_discriminator() -> None:
    op = BatchOp.create_op(ReminderFields(title="hello"))
    dumped = op.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"op": "create", "fields": {"title": "hello"}}


def test_batch_op_update_includes_uuid() -> None:
    op = BatchOp.update_op("U-1", ReminderFields(is_completed=True))
    dumped = op.model_dump(by_alias=True, exclude_none=True)
    assert dumped == {"op": "update", "uuid": "U-1", "fields": {"is_completed": True}}


def test_batch_result_allows_missing_last_modified_for_delete() -> None:
    res = BatchResult.model_validate({"index": 0, "ok": True, "uuid": "U-1"})
    assert res.last_modified is None
    assert res.error is None


def test_helper_reminder_rejects_bad_date() -> None:
    with pytest.raises(ValueError):
        HelperReminder.model_validate({
            "uuid": "U-1",
            "title": "x",
            "notes": "",
            "due_date": "not-a-date",
            "start_date": None,
            "is_completed": False,
            "completion_date": None,
            "last_modified": "2026-05-30T10:00:00Z",
        })


def test_calendar_summary_parses() -> None:
    raw = {"calendar_id": "CAL-1", "title": "Irma · Inbox"}
    cs = CalendarSummary.model_validate(raw)
    assert cs.calendar_id == "CAL-1"
    assert cs.title == "Irma · Inbox"
