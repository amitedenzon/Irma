"""LeadAgent — horizon-aware PMO synthesis.

Given a Horizon, builds a per-window SynthesisContext, composes a prompt
against the Irma persona, calls LLMClient.complete(), parses the response
to a Brief, caches it keyed on (horizon, inputs_hash), and returns. One
JSON-parse retry; second failure raises BriefSynthesisError.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final

import structlog
from pydantic import ValidationError

from irma_api.agents.llm import ChatTurn, LLMClient, TextResult
from irma_api.agents.prompts import load_prompt
from irma_api.config import Settings
from irma_api.models.brief import Brief, Horizon
from irma_api.models.project import Project, ProjectStatus
from irma_api.models.signal import Signal
from irma_api.models.task import Task, TaskStatus
from irma_api.store.repos.brief_cache_repo import BriefCacheRepo
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore

logger = structlog.get_logger(__name__)


class BriefSynthesisError(RuntimeError):
    """LLM failed to produce a valid Brief after one retry."""


_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")


def _strip_fences(text: str) -> str:
    stripped = _FENCE_RE.sub("", text.strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _parse_brief(text: str) -> Brief:
    cleaned = _strip_fences(text)
    try:
        return Brief.model_validate_json(cleaned)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("lead_agent.parse_failed", error=str(exc)[:200], head=cleaned[:200])
        raise BriefSynthesisError(str(exc)) from exc


@dataclass(frozen=True)
class SynthesisContext:
    horizon: Horizon
    today: date
    window_start: date
    window_end: date | None
    projects: list[Project]
    tasks: list[Task]
    signals: list[Signal]


def _window_for(horizon: Horizon, today: date) -> tuple[date, date | None]:
    if horizon == "day":
        return today, today
    if horizon == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if horizon == "month":
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
        return start, end
    return today, None


def _inputs_hash(ctx: SynthesisContext) -> str:
    parts: list[str] = [ctx.horizon, ctx.today.isoformat()]
    for p in sorted(ctx.projects, key=lambda x: x.id):
        parts.append(f"p:{p.id}:{p.updated_at.isoformat()}")
    for t in sorted(ctx.tasks, key=lambda x: x.id):
        parts.append(f"t:{t.id}:{t.updated_at.isoformat()}")
    for s in sorted(ctx.signals, key=lambda x: x.hash_key()):
        parts.append(f"s:{s.hash_key()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class LeadAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        store: SignalStore,
        max_tokens: int = 1500,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._store = store
        self._max_tokens = max_tokens

    async def synthesize(self, horizon: Horizon) -> Brief:
        ctx = await self._build_context(horizon)
        cache = BriefCacheRepo(self._store.connection)
        inputs_hash = _inputs_hash(ctx)
        cached = await cache.get(horizon, inputs_hash=inputs_hash)
        if cached is not None:
            logger.info("lead_agent.cache_hit", horizon=horizon)
            return cached

        if not ctx.projects and not ctx.tasks and not ctx.signals:
            brief = self._empty_brief(horizon)
            await cache.put(horizon, inputs_hash=inputs_hash, brief=brief)
            return brief

        brief = await self._call_and_parse(ctx)
        await cache.put(horizon, inputs_hash=inputs_hash, brief=brief)
        logger.info("lead_agent.brief_ready", horizon=horizon, conflicts=len(brief.conflicts))
        return brief

    async def _build_context(self, horizon: Horizon) -> SynthesisContext:
        today = datetime.now(UTC).date()
        start, end = _window_for(horizon, today)

        prepo = ProjectRepo(self._store.connection)
        trepo = TaskRepo(self._store.connection)
        projects = await prepo.list(statuses=[ProjectStatus.ACTIVE])

        open_statuses = [TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED]
        if horizon == "all":
            tasks = await trepo.list(statuses=open_statuses)
        else:
            scheduled = await trepo.list(
                statuses=open_statuses,
                scheduled_from=start,
                scheduled_to=end,
            )
            due_soon = await trepo.list(statuses=open_statuses, due_before=end)
            by_id = {t.id: t for t in scheduled}
            for t in due_soon:
                by_id.setdefault(t.id, t)
            tasks = list(by_id.values())

        sig_limit = {"day": 50, "week": 200, "month": 500, "all": 0}[horizon]
        signals: list[Signal] = (
            [] if sig_limit == 0 else await self._store.latest_signals(limit=sig_limit)
        )
        return SynthesisContext(
            horizon=horizon,
            today=today,
            window_start=start,
            window_end=end,
            projects=projects,
            tasks=tasks,
            signals=signals,
        )

    async def _call_and_parse(self, ctx: SynthesisContext) -> Brief:
        system = load_prompt("irma_persona")
        user = self._compose_user_message(ctx)
        messages: list[ChatTurn] = [ChatTurn(role="user", content=user)]

        outcome = await self._llm.complete(
            system=system, messages=messages, max_tokens=self._max_tokens
        )
        text = outcome.text if isinstance(outcome, TextResult) else ""
        try:
            return _parse_brief(text)
        except BriefSynthesisError:
            messages.append(ChatTurn(role="assistant", content=text))
            messages.append(
                ChatTurn(
                    role="user",
                    content=(
                        "Your previous reply did not parse as the required JSON "
                        "object. Reply with ONLY the JSON object now."
                    ),
                )
            )
            retry_outcome = await self._llm.complete(
                system=system, messages=messages, max_tokens=self._max_tokens
            )
            retry_text = (
                retry_outcome.text if isinstance(retry_outcome, TextResult) else ""
            )
            return _parse_brief(retry_text)

    def _compose_user_message(self, ctx: SynthesisContext) -> str:
        lines: list[str] = [
            f"HORIZON: {ctx.horizon}",
            f"TODAY: {ctx.today.isoformat()}",
        ]
        if ctx.window_end:
            lines.append(f"WINDOW: {ctx.window_start} → {ctx.window_end}")
        else:
            lines.append("WINDOW: all time")

        lines.append("")
        lines.append("ACTIVE PROJECTS:")
        for p in ctx.projects:
            target = f"target {p.target_date.isoformat()}" if p.target_date else "no target"
            lines.append(f"  • [{p.id}] {p.name}  priority={p.priority}  {target}")
            for g in p.goals:
                lines.append(f"      goal: {g}")

        lines.append("")
        lines.append("TASKS IN WINDOW:")
        if ctx.tasks:
            for t in ctx.tasks:
                bits = [f"status={t.status.value}"]
                if t.due_date:
                    bits.append(f"due={t.due_date.isoformat()}")
                if t.scheduled_for:
                    bits.append(f"sched={t.scheduled_for.isoformat()}")
                if t.estimated_minutes:
                    bits.append(f"est={t.estimated_minutes}m")
                lines.append(
                    f"  • [{t.id}] (project {t.project_id})  {t.title}  [{', '.join(bits)}]"
                )
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("CALENDAR SIGNALS IN WINDOW:")
        if ctx.signals:
            for s in ctx.signals:
                lines.append(
                    f"  • {s.ts.isoformat()}  {s.title}" + (f" — {s.detail}" if s.detail else "")
                )
        else:
            lines.append("  (none)")

        now_iso = datetime.now(UTC).isoformat()
        lines.append("")
        lines.append(
            f"Produce the Brief JSON now. Use generated_at = {now_iso} and "
            f'horizon = "{ctx.horizon}".'
        )
        return "\n".join(lines)

    def _empty_brief(self, horizon: Horizon) -> Brief:
        return Brief(
            horizon=horizon,
            generated_at=datetime.now(UTC),
            focus=[],
            project_status=[],
            conflicts=[],
            recommendation="Add a project to get started.",
            narrative="",
        )
