"""ScheduledBriefQueue: next-8am computation, dedup, cancel/replace, rollover."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from irma_api.models.daily_brief import DailyBrief
from irma_api.runtime.brief_queue import ScheduledBriefQueue, next_brief_time

# --------------------------------------------------------------------------- #
# next_brief_time — pure
# --------------------------------------------------------------------------- #

def test_next_brief_time_later_today() -> None:
    now = datetime(2026, 6, 1, 6, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    nxt = next_brief_time(now, hour=8, timezone="Asia/Jerusalem")
    assert nxt == datetime(2026, 6, 1, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))


def test_next_brief_time_rolls_to_tomorrow_when_past() -> None:
    now = datetime(2026, 6, 1, 23, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    nxt = next_brief_time(now, hour=8, timezone="Asia/Jerusalem")
    assert nxt == datetime(2026, 6, 2, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))


def test_next_brief_time_exactly_at_hour_rolls_forward() -> None:
    now = datetime(2026, 6, 1, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))
    nxt = next_brief_time(now, hour=8, timezone="Asia/Jerusalem")
    assert nxt.date() == date(2026, 6, 2)


def test_next_brief_time_accepts_utc_input_other_tz() -> None:
    # 05:30 UTC == 08:30 IDT, so the next 08:00 IDT is the following day.
    now = datetime(2026, 6, 1, 5, 30, tzinfo=UTC)
    nxt = next_brief_time(now, hour=8, timezone="Asia/Jerusalem")
    assert nxt == datetime(2026, 6, 2, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))


# --------------------------------------------------------------------------- #
# ScheduledBriefQueue.ensure_queued
# --------------------------------------------------------------------------- #

from irma_api.runtime.brief_queue import QueuedBrief  # noqa: E402
from tests.conftest import make_profile_cache  # noqa: E402


class _FakeService:
    def __init__(self, fingerprint: str = "fp1") -> None:
        self.fingerprint = fingerprint
        self.prepare_calls = 0
        self.render_calls = 0

    async def prepare(self, for_date: date) -> tuple[str, object]:
        self.prepare_calls += 1
        return self.fingerprint, ("inputs", for_date)

    async def render(self, inputs: object, for_date: date) -> DailyBrief:
        self.render_calls += 1
        return DailyBrief(generated_at=datetime.now(UTC), narrative="hello")


class _FakeSender:
    def __init__(self, cancel_error: Exception | None = None) -> None:
        self.scheduled: list[dict] = []
        self.cancelled: list[str] = []
        self._cancel_error = cancel_error
        self._n = 0

    async def schedule_email(self, *, subject, body, html, scheduled_at) -> str:
        self._n += 1
        self.scheduled.append(
            {"subject": subject, "body": body, "html": html, "scheduled_at": scheduled_at}
        )
        return f"email_{self._n}"

    async def cancel_email(self, email_id: str) -> None:
        if self._cancel_error is not None:
            raise self._cancel_error
        self.cancelled.append(email_id)


class _FakeStore:
    def __init__(self, state: QueuedBrief | None = None) -> None:
        self.state = state

    def load(self) -> QueuedBrief | None:
        return self.state

    def save(self, state: QueuedBrief) -> None:
        self.state = state

    def clear(self) -> None:
        self.state = None


_NOW_IL = datetime(2026, 6, 1, 23, 0, tzinfo=ZoneInfo("Asia/Jerusalem"))


def _queue(service, sender, store, **profile_kw):
    profile_kw.setdefault("timezone", "Asia/Jerusalem")
    profile_kw.setdefault("brief_hour", 8)
    profile_kw.setdefault("daily_brief_enabled", True)
    return ScheduledBriefQueue(
        service=service,
        sender=sender,
        state_store=store,
        profile_cache=make_profile_cache(**profile_kw),
        now=lambda: _NOW_IL,
    )


@pytest.mark.asyncio
async def test_first_run_schedules_for_next_brief_hour() -> None:
    svc, sender, store = _FakeService(), _FakeSender(), _FakeStore()
    result = await _queue(svc, sender, store).ensure_queued()

    assert result["queued"] is True
    assert len(sender.scheduled) == 1
    assert sender.scheduled[0]["scheduled_at"] == datetime(
        2026, 6, 2, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem")
    )
    assert sender.cancelled == []
    assert store.state is not None
    assert store.state.target_date == date(2026, 6, 2)
    assert store.state.email_id == "email_1"


_TARGET_ISO = datetime(2026, 6, 2, 8, 0, tzinfo=ZoneInfo("Asia/Jerusalem")).isoformat()


@pytest.mark.asyncio
async def test_unchanged_fingerprint_is_noop() -> None:
    svc, sender = _FakeService(fingerprint="same"), _FakeSender()
    store = _FakeStore(
        QueuedBrief(target_date=date(2026, 6, 2), fingerprint="same", email_id="old", scheduled_at=_TARGET_ISO)
    )
    result = await _queue(svc, sender, store).ensure_queued()

    assert result["queued"] is False
    assert svc.render_calls == 0
    assert sender.scheduled == []
    assert sender.cancelled == []


@pytest.mark.asyncio
async def test_changed_fingerprint_cancels_old_and_reschedules() -> None:
    svc, sender = _FakeService(fingerprint="new"), _FakeSender()
    store = _FakeStore(
        QueuedBrief(target_date=date(2026, 6, 2), fingerprint="old", email_id="old_id", scheduled_at=_TARGET_ISO)
    )
    result = await _queue(svc, sender, store).ensure_queued()

    assert result["queued"] is True
    assert sender.cancelled == ["old_id"]
    assert len(sender.scheduled) == 1
    assert store.state.email_id == "email_1"
    assert store.state.fingerprint == "new"


@pytest.mark.asyncio
async def test_brief_hour_change_reschedules_even_if_content_unchanged() -> None:
    # Same content + same delivery day, but the user moved the brief hour:
    # the previously-queued email is at the wrong time and must be replaced.
    svc, sender = _FakeService(fingerprint="same"), _FakeSender()
    stale_iso = datetime(2026, 6, 2, 7, 0, tzinfo=ZoneInfo("Asia/Jerusalem")).isoformat()
    store = _FakeStore(
        QueuedBrief(target_date=date(2026, 6, 2), fingerprint="same", email_id="old_id", scheduled_at=stale_iso)
    )
    result = await _queue(svc, sender, store, brief_hour=8).ensure_queued()

    assert result["queued"] is True
    assert sender.cancelled == ["old_id"]
    assert store.state.scheduled_at == _TARGET_ISO


@pytest.mark.asyncio
async def test_cancel_failure_keeps_existing_and_skips_replacement() -> None:
    # If the parked email can't be cancelled, do NOT schedule a replacement —
    # otherwise both fire at 8am. Keep the existing one (possibly stale) intact.
    svc = _FakeService(fingerprint="new")
    sender = _FakeSender(cancel_error=RuntimeError("cancel rejected"))
    prev = QueuedBrief(
        target_date=date(2026, 6, 2), fingerprint="old", email_id="old_id", scheduled_at=_TARGET_ISO
    )
    store = _FakeStore(prev)
    result = await _queue(svc, sender, store).ensure_queued()

    assert result["queued"] is False
    assert result["reason"] == "cancel_failed"
    assert sender.scheduled == []  # no duplicate scheduled
    assert store.state is prev  # state untouched — the old email still owns 8am


@pytest.mark.asyncio
async def test_rollover_to_new_day_does_not_cancel_sent_email() -> None:
    # Yesterday's queued email already fired; today's target is a new date.
    svc, sender = _FakeService(), _FakeSender()
    store = _FakeStore(
        QueuedBrief(target_date=date(2026, 6, 1), fingerprint="x", email_id="yest", scheduled_at="2026-06-01T08:00:00+03:00")
    )
    result = await _queue(svc, sender, store).ensure_queued()

    assert result["queued"] is True
    assert sender.cancelled == []  # never cancel a past day's (already-sent) email
    assert store.state.target_date == date(2026, 6, 2)


@pytest.mark.asyncio
async def test_disabled_profile_skips() -> None:
    svc, sender, store = _FakeService(), _FakeSender(), _FakeStore()
    result = await _queue(svc, sender, store, daily_brief_enabled=False).ensure_queued()

    assert result["queued"] is False
    assert svc.prepare_calls == 0
    assert sender.scheduled == []


@pytest.mark.asyncio
async def test_disabling_cancels_and_clears_existing_queued() -> None:
    svc, sender = _FakeService(), _FakeSender()
    store = _FakeStore(
        QueuedBrief(target_date=date(2026, 6, 2), fingerprint="x", email_id="live", scheduled_at=_TARGET_ISO)
    )
    result = await _queue(svc, sender, store, daily_brief_enabled=False).ensure_queued()

    assert result["queued"] is False
    assert sender.cancelled == ["live"]  # the parked email must not fire
    assert store.state is None  # state cleared


# --------------------------------------------------------------------------- #
# BriefQueueStateStore — JSON file persistence (survives restarts)
# --------------------------------------------------------------------------- #

from pathlib import Path  # noqa: E402

from irma_api.runtime.brief_queue import BriefQueueStateStore  # noqa: E402


def test_state_store_round_trips(tmp_path: Path) -> None:
    store = BriefQueueStateStore(tmp_path / "brief_queue.json")
    store.save(
        QueuedBrief(target_date=date(2026, 6, 2), fingerprint="abc", email_id="e9", scheduled_at=_TARGET_ISO)
    )
    loaded = store.load()
    assert loaded is not None
    assert loaded.target_date == date(2026, 6, 2)
    assert loaded.fingerprint == "abc"
    assert loaded.email_id == "e9"
    assert loaded.scheduled_at == _TARGET_ISO


def test_state_store_missing_file_returns_none(tmp_path: Path) -> None:
    assert BriefQueueStateStore(tmp_path / "nope.json").load() is None


def test_state_store_malformed_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "brief_queue.json"
    p.write_text("{ not valid json")
    assert BriefQueueStateStore(p).load() is None
