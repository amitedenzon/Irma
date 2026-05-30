"""DailyBriefJob: date-keyed idempotency + force override."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from irma_api.config import Settings
from irma_api.models.daily_brief import DailyBrief
from irma_api.runtime.daily_job import DailyBriefJob


class _FakeService:
    def __init__(self) -> None:
        self.builds = 0

    async def build(self) -> DailyBrief:
        self.builds += 1
        return DailyBrief(generated_at=datetime.now(UTC), narrative="hi")


class _FakeSender:
    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def call(self, args: dict) -> str:
        self.sends.append(args)
        return "sent (message id fake-123)"


def _settings() -> Settings:
    return Settings(_env_file=None, irma_brief_timezone="Asia/Jerusalem")


@pytest.mark.asyncio
async def test_first_run_sends_and_records_date() -> None:
    svc, sender = _FakeService(), _FakeSender()
    job = DailyBriefJob(service=svc, sender=sender, settings=_settings())
    result = await job.run_once()
    assert result["sent"] is True
    assert len(sender.sends) == 1
    assert "subject" in sender.sends[0] and "body" in sender.sends[0]
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    assert job.last_sent_date == today


@pytest.mark.asyncio
async def test_second_run_same_day_is_skipped() -> None:
    svc, sender = _FakeService(), _FakeSender()
    job = DailyBriefJob(service=svc, sender=sender, settings=_settings())
    job.last_sent_date = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    result = await job.run_once()
    assert result["sent"] is False
    assert sender.sends == []
    assert svc.builds == 0


@pytest.mark.asyncio
async def test_force_bypasses_idempotency() -> None:
    svc, sender = _FakeService(), _FakeSender()
    job = DailyBriefJob(service=svc, sender=sender, settings=_settings())
    job.last_sent_date = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    result = await job.run_once(force=True)
    assert result["sent"] is True
    assert len(sender.sends) == 1
