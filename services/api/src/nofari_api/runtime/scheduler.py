"""APScheduler wrapper. Periodic observer re-runs via AsyncIOScheduler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = structlog.get_logger(__name__)


class Scheduler:
    """Owns the AsyncIOScheduler instance for the process lifetime."""

    def __init__(
        self,
        refresh_minutes: int,
        on_tick: Callable[[], Awaitable[None]],
    ) -> None:
        self._sched = AsyncIOScheduler()
        self._refresh_minutes = refresh_minutes
        self._on_tick = on_tick

    def start(self) -> None:
        self._sched.add_job(
            self._on_tick,
            trigger=IntervalTrigger(minutes=self._refresh_minutes),
            id="nofari-refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self._sched.start()
        logger.info("scheduler.started", refresh_minutes=self._refresh_minutes)

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)
            logger.info("scheduler.stopped")
