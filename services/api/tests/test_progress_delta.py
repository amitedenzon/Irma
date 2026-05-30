"""compute_progress: per-project day-over-day delta vs a baseline snapshot."""

from __future__ import annotations

from datetime import UTC, date, datetime

from irma_api.agents.daily_brief import compute_progress
from irma_api.models.project import Project, ProjectStatus
from irma_api.models.task import Task, TaskStatus
from irma_api.store.repos.snapshot_repo import DailySnapshot


def _project(pid: str, name: str) -> Project:
    now = datetime(2026, 5, 30, tzinfo=UTC)
    return Project(
        id=pid,
        name=name,
        description="",
        status=ProjectStatus.ACTIVE,
        priority=2,
        calendar_keywords=[],
        goals=[],
        target_date=None,
        created_at=now,
        updated_at=now,
    )


def _task(tid: str, pid: str, status: TaskStatus) -> Task:
    now = datetime(2026, 5, 30, tzinfo=UTC)
    return Task(
        id=tid,
        project_id=pid,
        title=f"task {tid}",
        notes="",
        status=status,
        due_date=None,
        scheduled_for=None,
        estimated_minutes=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def test_no_baseline_reports_absolute_counts() -> None:
    projects = [_project("p1", "Alpha")]
    tasks = [_task("t1", "p1", TaskStatus.TODO), _task("t2", "p1", TaskStatus.DONE)]
    out = compute_progress(projects, tasks, baseline=None)
    assert len(out) == 1
    assert out[0].project_name == "Alpha"
    assert out[0].open_now == 1
    assert out[0].done_now == 1
    assert out[0].completed_since == 0
    assert out[0].added_since == 0


def test_completed_since_counts_newly_done_ids() -> None:
    baseline = DailySnapshot(
        snapshot_date=date(2026, 5, 29),
        per_project_counts={"p1": {"open": 2, "done": 0}},
        completed_task_ids=[],
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    projects = [_project("p1", "Alpha")]
    tasks = [_task("t1", "p1", TaskStatus.DONE), _task("t2", "p1", TaskStatus.TODO)]
    out = compute_progress(projects, tasks, baseline=baseline)
    assert out[0].completed_since == 1  # t1 newly done
    assert out[0].open_now == 1
    assert out[0].done_now == 1


def test_added_since_is_total_count_growth_floored_at_zero() -> None:
    baseline = DailySnapshot(
        snapshot_date=date(2026, 5, 29),
        per_project_counts={"p1": {"open": 1, "done": 0}},
        completed_task_ids=[],
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    projects = [_project("p1", "Alpha")]
    tasks = [
        _task("t1", "p1", TaskStatus.TODO),
        _task("t2", "p1", TaskStatus.TODO),
        _task("t3", "p1", TaskStatus.DONE),
    ]
    out = compute_progress(projects, tasks, baseline=baseline)
    assert out[0].added_since == 2  # 3 total now vs 1 before
