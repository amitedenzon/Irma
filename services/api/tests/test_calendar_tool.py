"""ReadCalendarTool: spec shape, error surface, formatting."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from irma_api.config import Settings
from irma_api.tools.base import ToolError
from irma_api.tools.calendar import ReadCalendarTool


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "google_oauth_client_id": "cid",
        "google_oauth_client_secret": "sec",
        "google_oauth_refresh_token": "rt",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.mark.asyncio
async def test_spec_has_only_optional_days_arg() -> None:
    tool = ReadCalendarTool(_settings())
    schema = tool.spec.input_schema
    assert set(schema["properties"].keys()) == {"days"}
    # No required fields — `days` defaults to 1 if omitted.
    assert "required" not in schema or schema["required"] == []


@pytest.mark.asyncio
async def test_missing_refresh_token_raises_unlinked() -> None:
    tool = ReadCalendarTool(_settings(google_oauth_refresh_token=None))
    with pytest.raises(ToolError) as exc_info:
        await tool.call({})
    assert exc_info.value.code == "calendar_unlinked"


@pytest.mark.asyncio
async def test_empty_result_returns_no_events_message() -> None:
    tool = ReadCalendarTool(_settings())

    async def fake_fetch(_self: Any, *_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return []

    with patch.object(ReadCalendarTool, "_fetch_events", new=fake_fetch):
        out = await tool.call({"days": 1})
    assert "No events" in out


@pytest.mark.asyncio
async def test_formats_events_one_per_line() -> None:
    tool = ReadCalendarTool(_settings())

    sample = [
        {
            "summary": "Standup",
            "start": {"dateTime": "2026-05-28T09:00:00Z"},
            "end": {"dateTime": "2026-05-28T09:30:00Z"},
            "location": "Zoom",
        },
        {
            "summary": "Lunch",
            "start": {"dateTime": "2026-05-28T12:00:00Z"},
            "end": {"dateTime": "2026-05-28T13:00:00Z"},
        },
    ]

    async def fake_fetch(_self: Any, *_a: Any, **_kw: Any) -> list[dict[str, Any]]:
        return sample

    with patch.object(ReadCalendarTool, "_fetch_events", new=fake_fetch):
        out = await tool.call({"days": 1})

    lines = out.splitlines()
    assert any("Standup" in line and "[Zoom]" in line for line in lines)
    assert any("Lunch" in line for line in lines)


@pytest.mark.asyncio
async def test_days_clamps_to_max() -> None:
    tool = ReadCalendarTool(_settings())
    captured: dict[str, Any] = {}

    async def fake_fetch(
        _self: Any,
        _client: Any,
        _user: Any,
        time_min: str,
        time_max: str,
    ) -> list[dict[str, Any]]:
        captured["time_min"] = time_min
        captured["time_max"] = time_max
        return []

    with patch.object(ReadCalendarTool, "_fetch_events", new=fake_fetch):
        await tool.call({"days": 999})

    # Clamp: max 14 days. The window between min and max should be ~14d.
    from datetime import datetime

    # Both are ISO strings emitted by datetime.isoformat() — re-parse cleanly.
    tmin = datetime.fromisoformat(captured["time_min"])
    tmax = datetime.fromisoformat(captured["time_max"])
    assert (tmax - tmin).days == 14
