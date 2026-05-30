"""render_daily_email: deterministic plain-text formatting."""

from __future__ import annotations

from datetime import UTC, date, datetime

from irma_api.agents.email_render import render_daily_email
from irma_api.models.brief import FocusItem, FocusKind
from irma_api.models.daily_brief import DailyBrief, LookaheadItem, ProjectProgress


def _brief(**kw) -> DailyBrief:
    base = dict(
        generated_at=datetime(2026, 5, 30, 5, 0, tzinfo=UTC),
        narrative="Good morning.",
        recommendation="Freeze code tonight.",
        conflicts=[],
        progress=[],
        today_focus=[],
        lookahead_tasks=[],
        calendar_text=None,
        has_baseline=True,
    )
    base.update(kw)
    return DailyBrief(**base)


def test_subject_uses_local_date() -> None:
    subject, _ = render_daily_email(_brief(), date(2026, 5, 30))
    assert subject == "Irma · Daily Brief — Sat 30 May"


def test_body_includes_sections_when_present() -> None:
    brief = _brief(
        progress=[
            ProjectProgress(
                project_id="p1", project_name="Alpha",
                completed_since=2, added_since=1, open_now=3, done_now=5,
            )
        ],
        today_focus=[FocusItem(kind=FocusKind.TASK, title="write spec")],
        lookahead_tasks=[
            LookaheadItem(title="submit", when="2026-06-01", kind="due", project_name="Alpha")
        ],
        conflicts=["MIT block clashes with deploy"],
    )
    _, body = render_daily_email(brief, date(2026, 5, 30))
    assert "Good morning." in body
    assert "PROGRESS SINCE YOUR LAST BRIEF" in body
    assert "Alpha" in body and "2 done" in body
    assert "TODAY'S FOCUS" in body and "write spec" in body
    assert "NEXT 3 DAYS" in body and "submit" in body
    assert "HEADS-UP" in body and "MIT block" in body
    assert "Freeze code tonight." in body


def test_first_brief_label_when_no_baseline() -> None:
    brief = _brief(
        has_baseline=False,
        progress=[
            ProjectProgress(
                project_id="p1", project_name="Alpha",
                completed_since=0, added_since=0, open_now=2, done_now=0,
            )
        ],
    )
    _, body = render_daily_email(brief, date(2026, 5, 30))
    assert "first brief" in body.lower()


def test_empty_sections_are_omitted() -> None:
    _, body = render_daily_email(_brief(), date(2026, 5, 30))
    assert "TODAY'S FOCUS" not in body
    assert "NEXT 3 DAYS" not in body
    assert "HEADS-UP" not in body
