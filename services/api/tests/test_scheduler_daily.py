"""Scheduler.add_daily_job / reschedule_daily_job behaviour."""

from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger

from irma_api.runtime.scheduler import DAILY_BRIEF_JOB_ID, Scheduler


def _make_sched() -> tuple[Scheduler, object]:
    async def _noop() -> None:
        return None

    sched = Scheduler(refresh_minutes=30, on_tick=_noop)
    return sched, _noop


@pytest.mark.asyncio
async def test_add_daily_job_registers_cron() -> None:
    async def _noop() -> None:
        return None

    sched = Scheduler(refresh_minutes=30, on_tick=_noop)
    sched.add_daily_job(_noop, hour=8, timezone="Asia/Jerusalem")

    job = sched._sched.get_job(DAILY_BRIEF_JOB_ID)
    assert job is not None
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "Asia/Jerusalem"
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "8"


@pytest.mark.asyncio
async def test_reschedule_daily_job_disabled_removes_job() -> None:
    """enabled=False removes the job; calling again is a no-op."""
    sched, noop = _make_sched()
    sched.add_daily_job(noop, hour=8, timezone="UTC")  # type: ignore[arg-type]

    assert sched._sched.get_job(DAILY_BRIEF_JOB_ID) is not None

    sched.reschedule_daily_job(hour=8, timezone="UTC", enabled=False)
    assert sched._sched.get_job(DAILY_BRIEF_JOB_ID) is None

    # Second call must not raise even though the job is already gone.
    sched.reschedule_daily_job(hour=8, timezone="UTC", enabled=False)
    assert sched._sched.get_job(DAILY_BRIEF_JOB_ID) is None


@pytest.mark.asyncio
async def test_reschedule_daily_job_updates_trigger() -> None:
    """enabled=True with a new hour/timezone updates the CronTrigger in place."""
    sched, noop = _make_sched()
    sched.add_daily_job(noop, hour=8, timezone="UTC")  # type: ignore[arg-type]

    sched.reschedule_daily_job(hour=9, timezone="Asia/Jerusalem", enabled=True)

    job = sched._sched.get_job(DAILY_BRIEF_JOB_ID)
    assert job is not None
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "Asia/Jerusalem"
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "9"


@pytest.mark.asyncio
async def test_reschedule_daily_job_readds_when_absent() -> None:
    """enabled=True re-adds the job when it was previously removed."""
    sched, noop = _make_sched()
    sched.add_daily_job(noop, hour=8, timezone="UTC")  # type: ignore[arg-type]
    sched.reschedule_daily_job(hour=8, timezone="UTC", enabled=False)
    assert sched._sched.get_job(DAILY_BRIEF_JOB_ID) is None

    sched.reschedule_daily_job(hour=10, timezone="America/New_York", enabled=True)

    job = sched._sched.get_job(DAILY_BRIEF_JOB_ID)
    assert job is not None
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "America/New_York"
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "10"


@pytest.mark.asyncio
async def test_startup_disabled_then_enable_via_patch() -> None:
    """Simulates the app.py startup sequence when daily_brief_enabled=False.

    The exact startup sequence is:
      1. add_daily_job(callback, ..., enabled=False) — stores callback, skips job

    Then a later PATCH with daily_brief_enabled=True calls:
      2. reschedule_daily_job(enabled=True, ...) — must re-add the job using
         the stored callback, not silently return.
    """
    sched, noop = _make_sched()

    # Step 1: startup while disabled — single call, no follow-up reschedule needed
    sched.add_daily_job(noop, hour=8, timezone="UTC", enabled=False)  # type: ignore[arg-type]

    # Job must be absent, but callback must be retained
    assert sched._sched.get_job(DAILY_BRIEF_JOB_ID) is None
    assert sched._daily_callback is not None

    # Step 2: user enables via PATCH
    sched.reschedule_daily_job(hour=7, timezone="Asia/Jerusalem", enabled=True)

    job = sched._sched.get_job(DAILY_BRIEF_JOB_ID)
    assert job is not None, "Job must exist after enable-after-disabled hot-reload"
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "Asia/Jerusalem"
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "7"
