"""DailyBriefService — assembles the emailed morning brief.

This module also exposes `compute_progress`, the pure per-project day-over-day
delta used by the brief and unit-tested independently.
"""

from __future__ import annotations

from irma_api.models.daily_brief import ProjectProgress
from irma_api.models.project import Project
from irma_api.models.task import Task, TaskStatus
from irma_api.store.repos.snapshot_repo import DailySnapshot


def compute_progress(
    projects: list[Project],
    tasks: list[Task],
    *,
    baseline: DailySnapshot | None,
) -> list[ProjectProgress]:
    """Per-project delta of `tasks` (all statuses) vs `baseline`.

    completed_since = newly-done task ids for the project not present in the
    baseline's completed set. added_since = growth in total task count for the
    project vs the baseline counts, floored at 0.
    """
    baseline_completed = set(baseline.completed_task_ids) if baseline else set()
    out: list[ProjectProgress] = []
    for p in projects:
        p_tasks = [t for t in tasks if t.project_id == p.id]
        done_ids_now = {t.id for t in p_tasks if t.status == TaskStatus.DONE}
        open_now = sum(1 for t in p_tasks if t.status != TaskStatus.DONE)
        done_now = len(done_ids_now)
        if baseline is not None:
            completed_since = len(done_ids_now - baseline_completed)
            base = baseline.per_project_counts.get(p.id, {"open": 0, "done": 0})
            base_total = int(base.get("open", 0)) + int(base.get("done", 0))
            added_since = max(0, (open_now + done_now) - base_total)
        else:
            # No prior snapshot: report absolute counts, no "since" deltas.
            completed_since = 0
            added_since = 0
        out.append(
            ProjectProgress(
                project_id=p.id,
                project_name=p.name,
                completed_since=completed_since,
                added_since=added_since,
                open_now=open_now,
                done_now=done_now,
            )
        )
    return out
