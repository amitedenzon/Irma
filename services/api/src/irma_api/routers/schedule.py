"""Schedule routines router — local metadata for cloud-dispatched mail routines."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from irma_api.agents.llm import ChatTurn, TextResult
from irma_api.agents.persona import build_routine_prefix, render_routine_system_prompt
from irma_api.runtime.profile_cache import current_profile
from irma_api.runtime.state import AgentState

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/schedule", tags=["schedule"])

# PROMPT_PREFIX is now built dynamically from the Profile at request time
# via build_routine_prefix(profile).  See get_prefix() below.


_MAX_TOOL_ITER = 20
_DAILY_BRIEF_ROUTINE_ID = "trig_0128d6voBA1V4YoHYqhtK1fE"
_WEEKLY_REVIEW_ROUTINE_ID = "trig_weekly_review_sat_2000"

_SEED: list[dict[str, Any]] = [
    {
        "id": "trig_0128d6voBA1V4YoHYqhtK1fE",
        "name": "Daily Brief",
        "cron": "30 4 * * *",
        "cron_human": "Every day",
        "enabled": True,
        "prompt": (
            "Task: your daily stand-up brief.\n\n"
            "DATA TO GATHER (3 tool calls total — do not call list_tasks per project):\n"
            "1. read_calendar for today + next 3 days (4 days total).\n"
            "2. list_projects — active only.\n"
            "3. list_tasks with no filters — returns all tasks across all projects.\n\n"
            "COMPOSE THE BRIEF with these sections, headings in ALL CAPS:\n\n"
            "TODAY'S SCHEDULE\n"
            "All of today's events in standard date format. If empty, say so.\n\n"
            "NEXT 3 DAYS\n"
            "Events for tomorrow through day+3, grouped by day. Omit days with nothing.\n\n"
            "PROGRESS DELTA\n"
            "What moved since yesterday: tasks completed today or yesterday (check completed_at), "
            "tasks newly in-progress or blocked. If nothing changed, say so briefly.\n\n"
            "OPEN & UPCOMING\n"
            "Tasks currently in-progress or due within 3 days, grouped by project. Skip done/archived.\n\n"
            "WATCH\n"
            "Conflicts, back-to-back blocks, tight transitions, or overdue tasks. Omit section entirely if none.\n\n"
            "RECOMMENDATION\n"
            "One short actionable sentence — the single most useful thing the operator can do today.\n\n"
            "Tight and scannable. Lead with what matters most."
        ),
    },
    {
        "id": "trig_weekly_review_sat_2000",
        "name": "Weekly Review",
        "cron": "0 20 * * 6",
        "cron_human": "Every Saturday at 20:00",
        "enabled": True,
        "prompt": (
            "This is a Saturday evening weekly retrospective.\n\n"
            "Reflect on the week that just ended. Be honest and specific — not generic.\n\n"
            "Focus on:\n"
            "- How productive was this week overall? Did meaningful work actually get done?\n"
            "- Task completion rate: what got done vs what was planned or overdue?\n"
            "- Time and schedule management: were heavy blocks well placed? Any conflicts or wasted transitions?\n"
            "- Project momentum: which projects moved, which stalled, which need attention next week?\n"
            "- One clear recommendation for next week based on what you observed.\n\n"
            "Tone: calm, honest, direct. Like a trusted advisor reviewing the week with you."
        ),
    },
]


class RoutineCreate(BaseModel):
    name: str
    cron: str
    cron_human: str
    prompt: str
    enabled: bool = True


class RoutineUpdate(BaseModel):
    name: str | None = None
    cron: str | None = None
    cron_human: str | None = None
    prompt: str | None = None
    enabled: bool | None = None


def _path(request: Request) -> Path:
    db: Path = request.app.state.settings.irma_db_path
    return db.parent / "schedules.json"


def _load(request: Request) -> list[dict[str, Any]]:
    p = _path(request)
    if not p.exists():
        p.write_text(json.dumps(_SEED, indent=2))
        return list(_SEED)
    data: list[dict[str, Any]] = json.loads(p.read_text())
    # Backfill missing seed entries; also sync prompt/cron_human for managed
    # routines whose seed content changed (identified by id).
    _MANAGED_IDS = {_DAILY_BRIEF_ROUTINE_ID, _WEEKLY_REVIEW_ROUTINE_ID}
    existing_ids = {r["id"] for r in data}
    changed = False
    for seed_entry in _SEED:
        if seed_entry["id"] not in existing_ids:
            data.append(seed_entry)
            changed = True
        elif seed_entry["id"] in _MANAGED_IDS:
            # Sync mutable display fields that may have changed in the seed.
            for r in data:
                if r["id"] == seed_entry["id"]:
                    for field in ("prompt", "cron_human"):
                        if r.get(field) != seed_entry.get(field):
                            r[field] = seed_entry[field]
                            changed = True
    if changed:
        _path(request).write_text(json.dumps(data, indent=2))
    return data


def _save(request: Request, routines: list[dict[str, Any]]) -> None:
    _path(request).write_text(json.dumps(routines, indent=2))


@router.get("/prefix")
async def get_prefix(request: Request) -> dict[str, str]:
    return {"prefix": build_routine_prefix(current_profile(request.app.state))}


@router.get("/routines")
async def list_routines(request: Request) -> list[dict[str, Any]]:
    return _load(request)


@router.post("/routines", status_code=201)
async def create_routine(body: RoutineCreate, request: Request) -> dict[str, Any]:
    routines = _load(request)
    routine: dict[str, Any] = {"id": str(uuid.uuid4()), **body.model_dump()}
    routines.append(routine)
    _save(request, routines)
    return routine


@router.patch("/routines/{routine_id}")
async def update_routine(
    routine_id: str, body: RoutineUpdate, request: Request
) -> dict[str, Any]:
    routines = _load(request)
    for r in routines:
        if r["id"] == routine_id:
            r.update(body.model_dump(exclude_none=True))
            _save(request, routines)
            return r
    raise HTTPException(status_code=404, detail="Routine not found")


@router.delete("/routines/{routine_id}", status_code=204)
async def delete_routine(routine_id: str, request: Request) -> None:
    routines = _load(request)
    filtered = [r for r in routines if r["id"] != routine_id]
    if len(filtered) == len(routines):
        raise HTTPException(status_code=404, detail="Routine not found")
    _save(request, filtered)


@router.post("/routines/{routine_id}/run")
async def run_routine(routine_id: str, request: Request) -> dict[str, Any]:
    routines = _load(request)
    routine = next((r for r in routines if r["id"] == routine_id), None)
    if routine is None:
        raise HTTPException(status_code=404, detail="Routine not found")

    bus = request.app.state.bus
    today = date.today()

    # --- Daily brief: reuse DailyBriefJob which pre-gathers all data in Python
    #     and makes a single LLM synthesis call — no tool loop, works with Ollama.
    daily_brief_job = getattr(request.app.state, "daily_brief_job", None)
    if routine_id == _DAILY_BRIEF_ROUTINE_ID and daily_brief_job is not None:
        await bus.publish(AgentState.THINKING)
        try:
            result = await daily_brief_job.run_once(force=True)
        except Exception as exc:
            await bus.publish(AgentState.ALERT)
            logger.exception("schedule.run_routine.daily_brief_failed", routine_id=routine_id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        await bus.publish(AgentState.IDLE)
        if not result.get("sent"):
            raise HTTPException(status_code=502, detail=str(result.get("reason", "not sent")))
        logger.info("schedule.run_routine.done", routine_id=routine_id, name=routine["name"])
        return {"sent": True}

    # --- Weekly review: delegate to WeeklyReviewJob (same instance as the scheduler uses).
    if routine_id == _WEEKLY_REVIEW_ROUTINE_ID:
        weekly_review_job = getattr(request.app.state, "weekly_review_job", None)
        if weekly_review_job is None:
            raise HTTPException(status_code=503, detail="Lead agent or email not configured")
        await bus.publish(AgentState.THINKING)
        try:
            result = await weekly_review_job.run_once(force=True)
        except Exception as exc:
            await bus.publish(AgentState.ALERT)
            logger.exception("schedule.run_routine.weekly_review_failed", routine_id=routine_id)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        await bus.publish(AgentState.IDLE)
        if not result.get("sent"):
            raise HTTPException(status_code=502, detail=str(result.get("reason", "not sent")))
        logger.info("schedule.run_routine.done", routine_id=routine_id, name=routine["name"])
        return {"sent": True}

    # --- Generic routines: single LLM synthesis call (no tool loop).
    #     Backend builds the context; LLM only writes the email body.
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not configured")

    send_tool = getattr(request.app.state, "send_email_tool", None)
    if send_tool is None:
        raise HTTPException(status_code=503, detail="Email not configured (RESEND_API_KEY / IRMA_USER_EMAIL)")

    from irma_api.tools.base import ToolError

    profile = current_profile(request.app.state)

    date_str = today.strftime("%d %B %Y")
    day_str = today.strftime("%A, %d %B %Y")
    subject = f"[Irma] {routine['name']} — {date_str}"
    system = render_routine_system_prompt(profile, day_str)

    await bus.publish(AgentState.THINKING)
    try:
        outcome = await llm.complete(
            system=system,
            messages=[ChatTurn(role="user", content=routine["prompt"])],
            max_tokens=800,
        )
        body = outcome.text if isinstance(outcome, TextResult) else ""
        if not body.strip():
            raise ValueError("LLM returned empty response")
        await send_tool.call({"subject": subject, "body": body})
    except ToolError as exc:
        await bus.publish(AgentState.ALERT)
        logger.warning("schedule.run_routine.send_failed", code=exc.code, detail=exc.detail)
        raise HTTPException(status_code=502, detail=f"{exc.code}: {exc.detail}") from exc
    except Exception as exc:
        await bus.publish(AgentState.ALERT)
        logger.exception("schedule.run_routine.failed", routine_id=routine_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    await bus.publish(AgentState.IDLE)
    logger.info("schedule.run_routine.done", routine_id=routine_id, name=routine["name"])
    return {"sent": True}
