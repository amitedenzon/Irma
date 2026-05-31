"""Schedule routines router.

Routines are stored in schedules.json next to irma.db. On first request the
file is seeded with the daily brief routine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/schedule", tags=["schedule"])

_SEED: list[dict[str, Any]] = [
    {
        "id": "trig_0128d6voBA1V4YoHYqhtK1fE",
        "name": "Daily Brief",
        "cron": "30 4 * * *",
        "cron_human": "Daily at 7:30 AM (Israel time)",
        "enabled": True,
        "prompt": (
            "You are Irma — Amit's calm, precise, slightly proactive personal assistant. "
            "Your task is to generate his daily brief and save it as a Gmail draft so it "
            "can be sent at 8:00 AM Israel time.\n\n"
            "Steps:\n\n"
            "1. Get today's date by running `date` in Bash. Then use Google Calendar to "
            "list all events across all calendars for today (full day, midnight to midnight "
            "local time).\n\n"
            "2. Synthesize a brief in Irma's voice: calm, terse, forward-looking. Use this structure:\n\n"
            "   Focus: what Amit should prioritize today given his schedule\n"
            "   Schedule: every event, using these exact formats:\n"
            "     - Timed same-day:  dd/MM (Day), HH:mm-HH:mm → title\n"
            "     - All-day single:  dd/MM (Day) → title\n"
            "     - All-day multi:   dd/MM - dd/MM (Day-Day) → title  "
            "[Google end-dates are exclusive — subtract 1 day to display correctly]\n"
            "   Watch: conflicts, back-to-back blocks, or tight transitions worth flagging. "
            "If none, omit this section.\n"
            "   Recommendation: one short actionable sentence.\n\n"
            "3. Create a Gmail draft:\n"
            "   - To: amit.edenzon@gmail.com\n"
            "   - Subject: [Irma] Daily Brief — [DD Month YYYY, e.g. 01 June 2026]\n"
            "   - Body: the brief in plain text, no markdown\n\n"
            "Keep it tight. Readable in under 2 minutes. No filler. If the day is light, say so."
        ),
    }
]


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


@router.get("/routines")
async def list_routines(request: Request) -> list[dict[str, Any]]:
    return _load(request)
