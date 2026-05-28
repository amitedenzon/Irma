"""CreateCalendarEventTool: spec shape, validation, success path."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from irma_api.config import Settings
from irma_api.tools.base import ToolError
from irma_api.tools.calendar import CreateCalendarEventTool


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "google_oauth_client_id": "cid",
        "google_oauth_client_secret": "sec",
        "google_oauth_refresh_token": "rt",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.mark.asyncio
async def test_spec_requires_summary_start_end() -> None:
    tool = CreateCalendarEventTool(_settings())
    schema = tool.spec.input_schema
    assert {"summary", "start", "end"}.issubset(set(schema["required"]))
    assert {"description", "location"}.isdisjoint(set(schema["required"]))


@pytest.mark.asyncio
async def test_missing_refresh_token_raises_unlinked() -> None:
    tool = CreateCalendarEventTool(_settings(google_oauth_refresh_token=None))
    with pytest.raises(ToolError) as exc_info:
        await tool.call(
            {"summary": "x", "start": "2026-05-28T10:00:00Z", "end": "2026-05-28T11:00:00Z"}
        )
    assert exc_info.value.code == "calendar_unlinked"


@pytest.mark.asyncio
async def test_end_before_start_raises_invalid_args() -> None:
    tool = CreateCalendarEventTool(_settings())
    with pytest.raises(ToolError) as exc_info:
        await tool.call(
            {
                "summary": "x",
                "start": "2026-05-28T12:00:00Z",
                "end": "2026-05-28T11:00:00Z",
            }
        )
    assert exc_info.value.code == "invalid_args"


@pytest.mark.asyncio
async def test_unparseable_start_raises_invalid_args() -> None:
    tool = CreateCalendarEventTool(_settings())
    with pytest.raises(ToolError) as exc_info:
        await tool.call(
            {"summary": "x", "start": "not-a-date", "end": "2026-05-28T11:00:00Z"}
        )
    assert exc_info.value.code == "invalid_args"


@pytest.mark.asyncio
async def test_success_returns_html_link() -> None:
    tool = CreateCalendarEventTool(_settings())
    captured: dict[str, Any] = {}

    async def fake_insert(
        _self: Any, _client: Any, _user: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        captured["body"] = body
        return {"htmlLink": "https://calendar.example/x"}

    with patch.object(CreateCalendarEventTool, "_insert_event", new=fake_insert):
        out = await tool.call(
            {
                "summary": "Focus block",
                "start": "2026-05-28T10:00:00Z",
                "end": "2026-05-28T12:00:00Z",
                "description": "video model bench",
                "location": "home",
            }
        )

    assert "https://calendar.example/x" in out
    assert captured["body"]["summary"] == "Focus block"
    assert captured["body"]["start"] == {"dateTime": "2026-05-28T10:00:00Z"}
    assert captured["body"]["end"] == {"dateTime": "2026-05-28T12:00:00Z"}
    assert captured["body"]["description"] == "video model bench"
    assert captured["body"]["location"] == "home"
