"""Scheduler.add_daily_job registers a CronTrigger at the configured hour/tz."""

from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger

from irma_api.runtime.scheduler import Scheduler


@pytest.mark.asyncio
async def test_add_daily_job_registers_cron() -> None:
    async def _noop() -> None:
        return None

    sched = Scheduler(refresh_minutes=30, on_tick=_noop)
    sched.add_daily_job(_noop, hour=8, timezone="Asia/Jerusalem")

    job = sched._sched.get_job("irma-daily-brief")
    assert job is not None
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "Asia/Jerusalem"
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "8"
