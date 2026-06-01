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
from irma_api.runtime.state import AgentState

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/schedule", tags=["schedule"])

# ---------------------------------------------------------------------------
# Default prefix prepended to every routine prompt at runtime (cloud agents).
# Not shown to the user in the UI — they only write the task-specific part.
# ---------------------------------------------------------------------------
PROMPT_PREFIX = """\
You are Irma — Amit's calm, precise, slightly proactive personal assistant. \
Your task is to prepare a scheduled email and save it as a Gmail draft for \
delivery at 8:00 AM Israel time.

Rules (always apply):
- Run `date` in Bash first to get today's date.
- Gmail draft: To: amit.edenzon@gmail.com.
- Subject: [Irma] {ROUTINE_NAME} — {DD Month YYYY}  (replace with the routine's name and today's date).
- Date formatting for calendar events:
    Timed same-day:  dd/MM (Day), HH:mm-HH:mm → title
    All-day single:  dd/MM (Day) → title
    All-day multi:   dd/MM - dd/MM (Day-Day) → title
    (Google all-day end-dates are exclusive — subtract 1 day when displaying.)
- Voice: calm, terse, forward-looking. No filler. Plain text, no markdown.\
"""


_MAX_TOOL_ITER = 20
_DAILY_BRIEF_ROUTINE_ID = "trig_0128d6voBA1V4YoHYqhtK1fE"

_SEED: list[dict[str, Any]] = [
    {
        "id": "trig_0128d6voBA1V4YoHYqhtK1fE",
        "name": "Daily Brief",
        "cron": "30 4 * * *",
        "cron_human": "Every day",
        "enabled": True,
        "prompt": (
            "Task: Amit's daily stand-up brief.\n\n"
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
            "One short actionable sentence — the single most useful thing Amit can do today.\n\n"
            "Tight and scannable. Lead with what matters most."
        ),
    }
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
    return data


def _save(request: Request, routines: list[dict[str, Any]]) -> None:
    _path(request).write_text(json.dumps(routines, indent=2))


@router.get("/prefix")
async def get_prefix() -> dict[str, str]:
    return {"prefix": PROMPT_PREFIX}


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

    # --- Generic routines: single LLM synthesis call (no tool loop).
    #     Backend builds the context; LLM only writes the email body.
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM not configured")

    send_tool = getattr(request.app.state, "send_email_tool", None)
    if send_tool is None:
        raise HTTPException(status_code=503, detail="Email not configured (RESEND_API_KEY / IRMA_USER_EMAIL)")

    from irma_api.tools.base import ToolError

    date_str = today.strftime("%d %B %Y")
    day_str = today.strftime("%A, %d %B %Y")
    subject = f"[Irma] {routine['name']} — {date_str}"
    system = (
        f"You are Irma — Amit's calm, precise, slightly proactive personal assistant.\n"
        f"Today is {day_str}.\n"
        "Write the body of a brief email to Amit based on the task below. "
        "Plain text only, no markdown. Calm, terse, actionable — no filler."
    )

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
