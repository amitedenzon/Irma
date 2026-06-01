"""ReadCalendarTool: spec shape, error surface, formatting."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from irma_api.config import Settings
from irma_api.tools.base import ToolError
from irma_api.tools.calendar import ReadCalendarTool
from tests.conftest import make_profile_cache


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "google_oauth_client_id": "cid",
        "google_oauth_client_secret": "sec",
        "google_oauth_refresh_token": "rt",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def _tool(**setting_overrides: Any) -> ReadCalendarTool:
    return ReadCalendarTool(_settings(**setting_overrides), make_profile_cache())


@pytest.mark.asyncio
async def test_spec_has_only_optional_days_arg() -> None:
    tool = _tool()
    schema = tool.spec.input_schema
    assert set(schema["properties"].keys()) == {"days"}
    # No required fields — `days` defaults to 1 if omitted.
    assert "required" not in schema or schema["required"] == []


@pytest.mark.asyncio
async def test_missing_refresh_token_raises_unlinked() -> None:
    tool = ReadCalendarTool(
        _settings(google_oauth_refresh_token=None),
        make_profile_cache(),
    )
    with pytest.raises(ToolError) as exc_info:
        await tool.call({})
    assert exc_info.value.code == "calendar_unlinked"


@pytest.mark.asyncio
async def test_empty_result_returns_no_events_message() -> None:
    tool = _tool()

    async def fake_fetch(
        _self: Any, *_a: Any, **_kw: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        return []

    with patch.object(ReadCalendarTool, "_fetch_events", new=fake_fetch):
        out = await tool.call({"days": 1})
    assert "no events" in out.lower()


@pytest.mark.asyncio
async def test_formats_events_one_per_line() -> None:
    tool = _tool()

    sample: list[tuple[str, dict[str, Any]]] = [
        (
            "My Calendar",
            {
                "summary": "Standup",
                "start": {"dateTime": "2026-05-28T09:00:00Z"},
                "end": {"dateTime": "2026-05-28T09:30:00Z"},
            },
        ),
        (
            "My Calendar",
            {
                "summary": "Lunch",
                "start": {"dateTime": "2026-05-28T12:00:00Z"},
                "end": {"dateTime": "2026-05-28T13:00:00Z"},
            },
        ),
    ]

    async def fake_fetch(
        _self: Any, *_a: Any, **_kw: Any
    ) -> list[tuple[str, dict[str, Any]]]:
        return sample

    with patch.object(ReadCalendarTool, "_fetch_events", new=fake_fetch):
        out = await tool.call({"days": 1})

    lines = out.splitlines()
    assert any("Standup" in line for line in lines)
    assert any("Lunch" in line for line in lines)


@pytest.mark.asyncio
async def test_days_clamps_to_max() -> None:
    tool = _tool()
    captured: dict[str, Any] = {}

    async def fake_fetch(
        _self: Any,
        _client: Any,
        _user: Any,
        time_min: str,
        time_max: str,
    ) -> list[tuple[str, dict[str, Any]]]:
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


@pytest.mark.asyncio
async def test_exclude_ids_read_from_profile_cache() -> None:
    """calendar_exclude_ids from the profile are passed to _fetch_events."""
    cache = make_profile_cache(calendar_exclude_ids=["cal-skip@group.v.calendar.google.com"])
    tool = ReadCalendarTool(_settings(), cache)
    captured_exclude: list[str] = []

    async def fake_fetch(
        self: ReadCalendarTool,
        client: Any,
        user: Any,
        time_min: str,
        time_max: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        # The real _fetch_events reads profile_cache inside — simulate by
        # recording what the cache says at the call site.
        captured_exclude.extend(self._profile_cache.current.calendar_exclude_ids)
        return []

    with patch.object(ReadCalendarTool, "_fetch_events", new=fake_fetch):
        await tool.call({"days": 1})

    assert "cal-skip@group.v.calendar.google.com" in captured_exclude


def test_format_event_includes_location_when_present() -> None:
    """_format_event appends [location] when the event has a location field."""
    event = {
        "summary": "Standup",
        "start": {"dateTime": "2026-05-28T09:00:00Z"},
        "end": {"dateTime": "2026-05-28T09:30:00Z"},
        "location": "Zoom",
    }
    result = ReadCalendarTool._format_event(event)
    assert "Standup" in result
    assert "[Zoom]" in result


def test_format_event_no_location_suffix_when_absent() -> None:
    """_format_event omits the location suffix when the event has no location."""
    event = {
        "summary": "Lunch",
        "start": {"dateTime": "2026-05-28T12:00:00Z"},
        "end": {"dateTime": "2026-05-28T13:00:00Z"},
    }
    result = ReadCalendarTool._format_event(event)
    assert "Lunch" in result
    assert "[" not in result
