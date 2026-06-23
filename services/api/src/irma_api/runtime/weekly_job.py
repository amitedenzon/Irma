"""WeeklyReviewJob — synthesizes and sends the Saturday evening weekly review.

Mirrors DailyBriefJob: idempotent (one send per calendar week), force=True for
on-demand runs from the schedule router.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.base import LeadAgentProtocol
from irma_api.agents.email_render import render_weekly_email, render_weekly_email_html
from irma_api.runtime.profile_cache import ProfileCache

logger = structlog.get_logger(__name__)

_WEEKLY_GUIDANCE = (
    "This is a Saturday evening weekly retrospective.\n\n"
    "Reflect on the week that just ended. Be honest and specific — not generic.\n\n"
    "Focus on:\n"
    "- How productive was this week overall? Did meaningful work actually get done?\n"
    "- Task completion rate: what got done vs what was planned or overdue?\n"
    "- Time and schedule management: were heavy blocks well placed? Any conflicts or wasted transitions?\n"
    "- Project momentum: which projects moved, which stalled, which need attention next week?\n"
    "- One clear recommendation for next week based on what you observed.\n\n"
    "Tone: calm, honest, direct. Like a trusted advisor reviewing the week with you."
)


class _Sender(Protocol):
    async def call(self, args: dict[str, str]) -> str: ...


class WeeklyReviewJob:
    def __init__(
        self,
        *,
        lead_agent: LeadAgentProtocol,
        sender: _Sender,
        profile_cache: ProfileCache,
    ) -> None:
        self._lead_agent: LeadAgentProtocol = lead_agent
        self._sender = sender
        self._profile_cache = profile_cache
        self.last_sent_week: date | None = None

    def _week_start(self) -> date:
        tz = ZoneInfo(self._profile_cache.current.timezone)
        today = datetime.now(tz).date()
        return today - timedelta(days=today.weekday())

    async def run_once(self, *, force: bool = False) -> dict[str, object]:
        week_start = self._week_start()
        if not force and self.last_sent_week == week_start:
            logger.info(
                "weekly_review.skipped", reason="already_sent", week_start=week_start.isoformat()
            )
            return {"sent": False, "reason": "already_sent"}

        brief = await self._lead_agent.synthesize("week", guidance=_WEEKLY_GUIDANCE)
        subject, body = render_weekly_email(brief, week_start)
        html = render_weekly_email_html(brief, week_start)
        result = await self._sender.call({"subject": subject, "body": body, "html": html})
        self.last_sent_week = week_start
        logger.info("weekly_review.sent", week_start=week_start.isoformat(), result=result)
        return {"sent": True, "result": result}
