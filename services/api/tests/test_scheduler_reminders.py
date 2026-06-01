from __future__ import annotations

import asyncio

import pytest

from irma_api.runtime.scheduler import Scheduler


@pytest.mark.asyncio
async def test_scheduler_accepts_optional_reminders_tick() -> None:
    refresh_calls = 0
    reminder_calls = 0

    async def refresh() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    async def reminders() -> None:
        nonlocal reminder_calls
        reminder_calls += 1

    sched = Scheduler(
        refresh_minutes=30,
        on_tick=refresh,
        reminders_interval_seconds=1,
        on_reminders_tick=reminders,
    )
    sched.start()
    await asyncio.sleep(1.5)
    sched.shutdown()
    assert reminder_calls >= 1
