"""DailyBriefService — assembles the emailed morning brief.

This module also exposes `compute_progress`, the pure per-project day-over-day
delta used by the brief and unit-tested independently.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.llm import ChatTurn, LLMClient, TextResult
from irma_api.agents.persona import build_owner_context
from irma_api.agents.prompts import load_prompt
from irma_api.models.brief import FocusItem, FocusKind
from irma_api.models.daily_brief import DailyBrief, LookaheadItem, ProjectProgress
from irma_api.models.profile import Profile
from irma_api.models.project import Project, ProjectStatus
from irma_api.models.task import Task, TaskStatus
from irma_api.runtime.profile_cache import ProfileCache
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


@dataclass(frozen=True)
class BriefInputs:
    """Everything needed to render a brief, collected without calling the LLM.

    Produced by :meth:`DailyBriefService.prepare` and consumed by
    :meth:`DailyBriefService.render`. The split lets the daily-brief queue
    fingerprint the inputs and skip re-synthesis when nothing changed.
    """

    profile: Profile
    today_focus: list[FocusItem]
    lookahead: list[LookaheadItem]
    calendar_text: str | None
    progress: list[ProjectProgress]
    baseline: DailySnapshot | None
    completed_task_ids: list[str]


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
        [str(c) for c in data.get("conflicts", []) if str(c).strip()],
    )


class DailyBriefService:
    def __init__(
        self,
        *,
        profile_cache: ProfileCache,
        llm: LLMClient,
        store: SignalStore,
        observers: list[Observer],
        bus: StateBus,
        calendar: ReadCalendarTool | None,
        max_tokens: int = 1200,
    ) -> None:
        self._profile_cache = profile_cache
        self._llm = llm
        self._store = store
        self._observers = observers
        self._bus = bus
        self._calendar = calendar
        self._max_tokens = max_tokens

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self._profile_cache.current.timezone)).date()

    async def build(self, for_date: date | None = None) -> DailyBrief:
        """Collect + synthesize a brief for ``for_date`` (default: today).

        The on-demand "Brief" button calls this with no argument. The scheduled
        queue passes the delivery morning so a brief generated tonight describes
        tomorrow.
        """
        target = for_date or self._today()
        _, inputs = await self.prepare(target)
        return await self.render(inputs, target)

    async def prepare(self, for_date: date) -> tuple[str, BriefInputs]:
        """Collect brief inputs for ``for_date`` without calling the LLM.

        Returns ``(fingerprint, inputs)``. The fingerprint covers exactly the
        data the email renders (progress, focus, lookahead, calendar) so an
        unchanged fingerprint means a previously-queued email is still current.
        """
        from irma_api.routers.signals import run_refresh  # local: avoid circular import

        try:
            await run_refresh(store=self._store, observers=self._observers, bus=self._bus)
        except Exception as exc:  # observers must never block the brief
            logger.warning("daily_brief.refresh_failed", error=str(exc))

        profile = self._profile_cache.current
        window_end = for_date + timedelta(days=profile.brief_lookahead_days)

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
            and (
                (t.due_date is not None and t.due_date <= for_date)
                or t.scheduled_for == for_date
            )
        ]

        today_focus_ids = {f.task_id for f in today_focus}
        lookahead: list[LookaheadItem] = []
        for t in all_tasks:
            if t.status not in _OPEN_STATUSES:
                continue
            if t.id in today_focus_ids:
                continue
            if t.due_date is not None and for_date < t.due_date <= window_end:
                lookahead.append(
                    LookaheadItem(
                        title=t.title,
                        when=t.due_date.isoformat(),
                        kind="due",
                        project_name=project_names.get(t.project_id),
                    )
                )
            elif t.scheduled_for is not None and for_date < t.scheduled_for <= window_end:
                lookahead.append(
                    LookaheadItem(
                        title=t.title,
                        when=t.scheduled_for.isoformat(),
                        kind="scheduled",
                        project_name=project_names.get(t.project_id),
                    )
                )
        lookahead.sort(key=lambda it: it.when)

        calendar_text = await self._read_calendar(for_date)

        baseline = await SnapshotRepo(self._store.connection).latest_before(for_date)
        progress = compute_progress(projects, all_tasks, baseline=baseline)

        inputs = BriefInputs(
            profile=profile,
            today_focus=today_focus,
            lookahead=lookahead,
            calendar_text=calendar_text,
            progress=progress,
            baseline=baseline,
            completed_task_ids=[t.id for t in all_tasks if t.status == TaskStatus.DONE],
        )
        return self._fingerprint(inputs, for_date), inputs

    async def render(self, inputs: BriefInputs, for_date: date) -> DailyBrief:
        """Synthesize the prose layer + persist the snapshot for ``for_date``."""
        narrative, recommendation, conflicts = await self._synthesize(
            profile=inputs.profile,
            today=for_date,
            progress=inputs.progress,
            today_focus=inputs.today_focus,
            lookahead=inputs.lookahead,
            calendar_text=inputs.calendar_text,
        )

        await SnapshotRepo(self._store.connection).upsert(
            for_date,
            per_project_counts={
                p.project_id: {"open": p.open_now, "done": p.done_now}
                for p in inputs.progress
            },
            completed_task_ids=inputs.completed_task_ids,
        )

        return DailyBrief(
            generated_at=datetime.now(UTC),
            narrative=narrative,
            recommendation=recommendation,
            conflicts=conflicts,
            progress=inputs.progress,
            today_focus=inputs.today_focus,
            lookahead_tasks=inputs.lookahead,
            calendar_text=inputs.calendar_text,
            has_baseline=inputs.baseline is not None,
        )

    @staticmethod
    def _fingerprint(inputs: BriefInputs, for_date: date) -> str:
        payload = {
            "for_date": for_date.isoformat(),
            "progress": [
                [p.project_id, p.completed_since, p.added_since, p.open_now, p.done_now]
                for p in inputs.progress
            ],
            "today_focus": [[f.title, f.due_date, f.project_name] for f in inputs.today_focus],
            "lookahead": [
                [it.title, it.when, it.kind, it.project_name] for it in inputs.lookahead
            ],
            "calendar_text": inputs.calendar_text or "",
            "has_baseline": inputs.baseline is not None,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _read_calendar(self, for_date: date) -> str | None:
        if self._calendar is None:
            return None
        try:
            text = await self._calendar.call({"days": 1, "start_date": for_date.isoformat()})
            return str(text)
        except ToolError as exc:
            logger.info("daily_brief.calendar_skipped", code=exc.code)
            return None

    async def _synthesize(
        self,
        *,
        profile: Profile,
        today: date,
        progress: list[ProjectProgress],
        today_focus: list[FocusItem],
        lookahead: list[LookaheadItem],
        calendar_text: str | None,
    ) -> tuple[str, str, list[str]]:
        base_system = load_prompt("daily_brief_system")
        owner_ctx = build_owner_context(profile)
        system = f"{base_system}\n\n{owner_ctx}"
        user = self._compose(profile, today, progress, today_focus, lookahead, calendar_text)
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
        profile: Profile,
        today: date,
        progress: list[ProjectProgress],
        today_focus: list[FocusItem],
        lookahead: list[LookaheadItem],
        calendar_text: str | None,
    ) -> str:
        lines: list[str] = [
            f"TODAY: {today.isoformat()}",
            "",
            "NOTE: The email template already renders all lists (progress, focus tasks,",
            "lookahead deadlines, calendar). Only write the prose layer — do NOT list",
            "individual events, tasks, or meetings in the narrative.",
            "",
            "PROGRESS SINCE LAST BRIEF (per project):",
        ]
        for p in progress:
            lines.append(
                f"  • {p.project_name}: {p.completed_since} completed, "
                f"{p.added_since} added — {p.open_now} open / {p.done_now} done"
            )
        lines.append("")
        lines.append("TODAY'S FOCUS (overdue + due today):")
        if today_focus:
            lines.extend(
                f"  • {f.title}"
                + (f" (due {f.due_date})" if f.due_date else "")
                for f in today_focus
            )
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append(f"NEXT {profile.brief_lookahead_days} DAYS (task deadlines):")
        if lookahead:
            lines.extend(f"  • {it.when} {it.title} ({it.kind})" for it in lookahead)
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("TODAY'S CALENDAR (shown for conflict detection only):")
        lines.append(calendar_text or "  (calendar unavailable)")
        return "\n".join(lines)
