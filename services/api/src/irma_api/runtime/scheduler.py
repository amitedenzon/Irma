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


def _make_cron_trigger(*, hour: int, timezone: str) -> CronTrigger:
    return CronTrigger(hour=hour, minute=0, timezone=timezone)


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
        timezone: str,
    ) -> None:
        """Register the once-a-day brief send at `hour`:00 in `timezone`.

        Safe to call before or after start(); APScheduler schedules it either
        way. Strict policy: the job only fires if the process is running at the
        trigger time — there is no catch-up for a missed morning.
        """
        self._daily_callback = callback
        self._sched.add_job(
            callback,
            trigger=_make_cron_trigger(hour=hour, timezone=timezone),
            id=DAILY_BRIEF_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("scheduler.daily_job_added", hour=hour, timezone=timezone)

    def reschedule_daily_job(
        self,
        *,
        hour: int,
        timezone: str,
        enabled: bool,
    ) -> None:
        """Hot-update the daily brief trigger without restarting the process.

        - ``enabled=False``: removes the job if it exists (no-op if absent).
        - ``enabled=True``: reschedules the existing job's trigger; if the job
          was previously removed, re-adds it using the callback stored during
          the last :meth:`add_daily_job` call.
        """
        job = self._sched.get_job(DAILY_BRIEF_JOB_ID)
        if not enabled:
            if job is not None:
                try:
                    self._sched.remove_job(DAILY_BRIEF_JOB_ID)
                    logger.info("scheduler.daily_job_removed")
                except JobLookupError:
                    pass  # already gone — safe to ignore
            return

        trigger = _make_cron_trigger(hour=hour, timezone=timezone)
        if job is not None:
            self._sched.reschedule_job(DAILY_BRIEF_JOB_ID, trigger=trigger)
            logger.info(
                "scheduler.daily_job_rescheduled", hour=hour, timezone=timezone
            )
        else:
            callback = getattr(self, "_daily_callback", None)
            if callback is None:
                logger.warning(
                    "scheduler.reschedule_daily_job.no_callback",
                    detail="add_daily_job was never called; cannot re-add the job",
                )
                return
            self._sched.add_job(
                callback,
                trigger=trigger,
                id=DAILY_BRIEF_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "scheduler.daily_job_readded", hour=hour, timezone=timezone
            )

    def shutdown(self) -> None:
        if self._sched.running:
            self._sched.shutdown(wait=False)
            logger.info("scheduler.stopped")
