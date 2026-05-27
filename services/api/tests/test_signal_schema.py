"""Signal + ScheduleItem schema invariants."""

from __future__ import annotations

from datetime import UTC, datetime

from irma_api.models.signal import ScheduleItem, Signal


def test_signal_hash_is_stable_and_order_independent() -> None:
    ts = datetime(2026, 5, 27, 9, 30, tzinfo=UTC)
    a = Signal(
        source="codebase",
        kind="commit",
        title="fix typo",
        ts=ts,
        meta={"hash": "abc", "repo": "video-wm", "insertions": 3, "deletions": 1},
    )
    b = Signal(
        source="codebase",
        kind="commit",
        title="fix typo",
        ts=ts,
        # Same data, different dict-insertion order.
        meta={"deletions": 1, "repo": "video-wm", "hash": "abc", "insertions": 3},
    )
    assert a.hash_key() == b.hash_key()


def test_signal_hash_differs_on_field_change() -> None:
    ts = datetime(2026, 5, 27, 9, 30, tzinfo=UTC)
    base = Signal(source="codebase", kind="commit", title="x", ts=ts, meta={})
    different_title = base.model_copy(update={"title": "y"})
    different_ts = base.model_copy(update={"ts": ts.replace(minute=31)})
    assert base.hash_key() != different_title.hash_key()
    assert base.hash_key() != different_ts.hash_key()


def test_schedule_item_optional_epic() -> None:
    item = ScheduleItem(ts=datetime.now(UTC), title="MIT 6.S191")
    assert item.epic is None
