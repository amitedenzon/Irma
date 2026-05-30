"""DailyBriefService — assembles the emailed morning brief.

This module also exposes `compute_progress`, the pure per-project day-over-day
delta used by the brief and unit-tested independently.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.llm import ChatTurn, LLMClient, TextResult
from irma_api.agents.prompts import load_prompt
from irma_api.config import Settings
from irma_api.models.brief import FocusItem, FocusKind
from irma_api.models.daily_brief import DailyBrief, LookaheadItem, ProjectProgress
from irma_api.models.project import Project, ProjectStatus
from irma_api.models.task import Task, TaskStatus
from irma_api.runtime.state import StateBus
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.snapshot_repo import DailySnapshot, SnapshotRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import ToolError

if TYPE_CHECKING:
    from irma_api.agents.base import Observer
    from irma_api.tools.calendar import ReadCalendarTool

logger = structlog.get_logger(__name__)

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")
_OPEN_STATUSES: Final = [TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED]


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


def _extract_json(text: str) -> str:
    stripped = _FENCE_RE.sub("", text.strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _parse_prose(text: str) -> tuple[str, str, list[str]]:
    data = json.loads(_extract_json(text))
    return (
        str(data["narrative"]),
        str(data["recommendation"]),
        [str(c) for c in data.get("conflicts", [])],
    )


class DailyBriefService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        store: SignalStore,
        observers: list[Observer],
        bus: StateBus,
        calendar: ReadCalendarTool | None,
        max_tokens: int = 1200,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._store = store
        self._observers = observers
        self._bus = bus
        self._calendar = calendar
        self._max_tokens = max_tokens

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self._settings.irma_brief_timezone)).date()

    async def build(self) -> DailyBrief:
        from irma_api.routers.signals import run_refresh  # local: avoid circular import

        try:
            await run_refresh(store=self._store, observers=self._observers, bus=self._bus)
        except Exception as exc:  # observers must never block the brief
            logger.warning("daily_brief.refresh_failed", error=str(exc))

        today = self._today()
        window_end = today + timedelta(days=self._settings.irma_brief_lookahead_days)

        prepo = ProjectRepo(self._store.connection)
        trepo = TaskRepo(self._store.connection)
        projects = await prepo.list(statuses=[ProjectStatus.ACTIVE])
        all_tasks = await trepo.list()
        project_names = {p.id: p.name for p in projects}

        today_focus = [
            FocusItem(
                kind=FocusKind.TASK,
                title=t.title,
                project_id=t.project_id,
                project_name=project_names.get(t.project_id),
                task_id=t.id,
                due_date=t.due_date.isoformat() if t.due_date else None,
                scheduled_for=t.scheduled_for.isoformat() if t.scheduled_for else None,
            )
            for t in all_tasks
            if t.status in _OPEN_STATUSES
            and (t.due_date == today or t.scheduled_for == today)
        ]

        lookahead: list[LookaheadItem] = []
        for t in all_tasks:
            if t.status not in _OPEN_STATUSES:
                continue
            if t.due_date is not None and today < t.due_date <= window_end:
                lookahead.append(
                    LookaheadItem(
                        title=t.title,
                        when=t.due_date.isoformat(),
                        kind="due",
                        project_name=project_names.get(t.project_id),
                    )
                )
            elif t.scheduled_for is not None and today < t.scheduled_for <= window_end:
                lookahead.append(
                    LookaheadItem(
                        title=t.title,
                        when=t.scheduled_for.isoformat(),
                        kind="scheduled",
                        project_name=project_names.get(t.project_id),
                    )
                )
        lookahead.sort(key=lambda it: it.when)

        calendar_text = await self._read_calendar()

        baseline = await SnapshotRepo(self._store.connection).latest_before(today)
        progress = compute_progress(projects, all_tasks, baseline=baseline)

        narrative, recommendation, conflicts = await self._synthesize(
            today=today,
            progress=progress,
            today_focus=today_focus,
            lookahead=lookahead,
            calendar_text=calendar_text,
        )

        await SnapshotRepo(self._store.connection).upsert(
            today,
            per_project_counts={
                p.project_id: {"open": p.open_now, "done": p.done_now} for p in progress
            },
            completed_task_ids=[t.id for t in all_tasks if t.status == TaskStatus.DONE],
        )

        return DailyBrief(
            generated_at=datetime.now(UTC),
            narrative=narrative,
            recommendation=recommendation,
            conflicts=conflicts,
            progress=progress,
            today_focus=today_focus,
            lookahead_tasks=lookahead,
            calendar_text=calendar_text,
            has_baseline=baseline is not None,
        )

    async def _read_calendar(self) -> str | None:
        if self._calendar is None:
            return None
        try:
            text = await self._calendar.call(
                {"days": self._settings.irma_brief_lookahead_days}
            )
            return str(text)
        except ToolError as exc:
            logger.info("daily_brief.calendar_skipped", code=exc.code)
            return None

    async def _synthesize(
        self,
        *,
        today: date,
        progress: list[ProjectProgress],
        today_focus: list[FocusItem],
        lookahead: list[LookaheadItem],
        calendar_text: str | None,
    ) -> tuple[str, str, list[str]]:
        system = load_prompt("irma_persona")
        user = self._compose(today, progress, today_focus, lookahead, calendar_text)
        messages = [ChatTurn(role="user", content=user)]
        outcome = await self._llm.complete(
            system=system, messages=messages, max_tokens=self._max_tokens
        )
        text = outcome.text if isinstance(outcome, TextResult) else ""
        try:
            return _parse_prose(text)
        except (KeyError, ValueError):
            messages.append(ChatTurn(role="assistant", content=text))
            messages.append(
                ChatTurn(
                    role="user",
                    content=(
                        "That did not parse. Reply with ONLY a JSON object: "
                        '{"narrative": str, "recommendation": str, "conflicts": [str]}'
                    ),
                )
            )
            retry = await self._llm.complete(
                system=system, messages=messages, max_tokens=self._max_tokens
            )
            retry_text = retry.text if isinstance(retry, TextResult) else ""
            return _parse_prose(retry_text)

    def _compose(
        self,
        today: date,
        progress: list[ProjectProgress],
        today_focus: list[FocusItem],
        lookahead: list[LookaheadItem],
        calendar_text: str | None,
    ) -> str:
        lines: list[str] = [
            f"TODAY: {today.isoformat()}",
            "You are writing the operator's morning brief email.",
            "",
            "PROGRESS SINCE LAST BRIEF (per project):",
        ]
        for p in progress:
            lines.append(
                f"  • {p.project_name}: {p.completed_since} completed, "
                f"{p.added_since} added — {p.open_now} open / {p.done_now} done"
            )
        lines.append("")
        lines.append("TODAY'S FOCUS:")
        if today_focus:
            lines.extend(f"  • {f.title}" for f in today_focus)
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"NEXT {self._settings.irma_brief_lookahead_days} DAYS (task deadlines):")
        if lookahead:
            lines.extend(f"  • {it.when} {it.title} ({it.kind})" for it in lookahead)
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("CALENDAR (next few days):")
        lines.append(calendar_text or "  (calendar unavailable)")
        lines.append("")
        lines.append(
            "Reply with ONLY a JSON object (no markdown fence): "
            '{"narrative": <2-3 warm sentences in Irma\'s voice summarising the day>, '
            '"recommendation": <one concrete suggestion>, '
            '"conflicts": [<zero or more short strings on clashes/overload>]}'
        )
        return "\n".join(lines)
