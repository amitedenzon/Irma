"""APScheduler wrapper. Periodic observer refresh + optional reminders sync."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = structlog.get_logger(__name__)

DAILY_BRIEF_JOB_ID = "irma-daily-brief"


def _make_cron_trigger(*, hour: int, minute: int = 0, timezone: str) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=timezone)


class Scheduler:
    def __init__(
        self,
        refresh_minutes: int,
        on_tick: Callable[[], Awaitable[None]],
        *,
        reminders_interval_seconds: int | None = None,
        on_reminders_tick: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._sched = AsyncIOScheduler()
        self._refresh_minutes = refresh_minutes
        self._on_tick = on_tick
        self._reminders_interval = reminders_interval_seconds
        self._on_reminders_tick = on_reminders_tick
        self._daily_callback: Callable[[], Awaitable[object]] | None = None

    def start(self) -> None:
        self._sched.add_job(
            self._on_tick,
            trigger=IntervalTrigger(minutes=self._refresh_minutes),
            id="irma-refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if self._reminders_interval and self._on_reminders_tick:
            self._sched.add_job(
                self._on_reminders_tick,
                trigger=IntervalTrigger(seconds=self._reminders_interval),
                id="irma-reminders-sync",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
        self._sched.start()
        logger.info(
            "scheduler.started",
            refresh_minutes=self._refresh_minutes,
            reminders_seconds=self._reminders_interval,
        )

    def add_daily_job(
        self,
        callback: Callable[[], Awaitable[object]],
        *,
        hour: int,
        minute: int = 0,
        timezone: str,
        enabled: bool = True,
    ) -> None:
        """Register the once-a-day brief send at `hour`:`minute` in `timezone`."""
        self._daily_callback = callback
        if not enabled:
            logger.info(
                "scheduler.daily_job_skipped_disabled", hour=hour, minute=minute, timezone=timezone
            )
            return
        self._sched.add_job(
            callback,
            trigger=_make_cron_trigger(hour=hour, minute=minute, timezone=timezone),
            id=DAILY_BRIEF_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("scheduler.daily_job_added", hour=hour, minute=minute, timezone=timezone)

    def reschedule_daily_job(
        self,
        *,
        hour: int,
        minute: int = 0,
        timezone: str,
        enabled: bool,
    ) -> None:
        """Hot-update the daily brief trigger without restarting the process."""
        job = self._sched.get_job(DAILY_BRIEF_JOB_ID)
        if not enabled:
            if job is not None:
                try:
                    self._sched.remove_job(DAILY_BRIEF_JOB_ID)
                    logger.info("scheduler.daily_job_removed")
                except JobLookupError:
                    pass
            return

        trigger = _make_cron_trigger(hour=hour, minute=minute, timezone=timezone)
        if job is not None:
            self._sched.reschedule_job(DAILY_BRIEF_JOB_ID, trigger=trigger)
            logger.info(
                "scheduler.daily_job_rescheduled", hour=hour, minute=minute, timezone=timezone
            )
        else:
            if self._daily_callback is None:
                logger.warning(
                    "scheduler.reschedule_daily_job.no_callback",
                    detail="add_daily_job was never called; cannot re-add the job",
                )
                return
            self._sched.add_job(
                self._daily_callback,
                trigger=trigger,
                id=DAILY_BRIEF_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "scheduler.daily_job_readded", hour=hour, minute=minute, timezone=timezone
            )

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)
            logger.info("scheduler.stopped")
