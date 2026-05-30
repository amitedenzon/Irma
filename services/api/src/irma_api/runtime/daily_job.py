"""DailyBriefJob — builds, renders, and sends the daily brief once per day.

The cron callback calls run_once() (idempotent: at most one send per local
calendar day). The on-demand endpoint calls run_once(force=True). Idempotency
state is in-memory: a strict 8am policy means a missed morning is simply not
sent — there is no startup catch-up.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.email_render import render_daily_email
from irma_api.config import Settings
from irma_api.models.daily_brief import DailyBrief

logger = structlog.get_logger(__name__)


class _Builder(Protocol):
    async def build(self) -> DailyBrief: ...


class _Sender(Protocol):
    async def call(self, args: dict[str, str]) -> str: ...


class DailyBriefJob:
    def __init__(self, *, service: _Builder, sender: _Sender, settings: Settings) -> None:
        self._service = service
        self._sender = sender
        self._tz = ZoneInfo(settings.irma_brief_timezone)
        self.last_sent_date: date | None = None

    def _today(self) -> date:
        return datetime.now(self._tz).date()

    async def run_once(self, *, force: bool = False) -> dict[str, object]:
        today = self._today()
        if not force and self.last_sent_date == today:
            logger.info("daily_brief.skipped", reason="already_sent", date=today.isoformat())
            return {"sent": False, "reason": "already_sent"}

        brief = await self._service.build()
        subject, body = render_daily_email(brief, today)
        result = await self._sender.call({"subject": subject, "body": body})
        self.last_sent_date = today
        logger.info("daily_brief.sent", date=today.isoformat(), result=result)
        return {"sent": True, "result": result}
