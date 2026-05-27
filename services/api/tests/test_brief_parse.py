"""Defensive JSON parsing + retry contract for LeadAgent."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nofari_api.agents.lead_agent import (
    BriefSynthesisError,
    LeadAgent,
    _parse_brief,
    _strip_fences,
)
from nofari_api.config import Settings
from nofari_api.models.brief import StandupBrief
from nofari_api.models.signal import Signal
from nofari_api.store.sqlite import SignalStore

_VALID_BRIEF_JSON = json.dumps(
    {
        "generated_at": "2026-05-27T10:00:00+00:00",
        "velocity": "Sustained churn on video-wm.",
        "blockers": [],
        "conflicts": [],
        "schedule": [],
        "recommendation": "Ship the eval script.",
        "narrative": "Good momentum. Keep going.",
    }
)


def test_strip_fences_handles_fenced_input() -> None:
    fenced = f"```json\n{_VALID_BRIEF_JSON}\n```"
    parsed = json.loads(_strip_fences(fenced))
    assert parsed["velocity"].startswith("Sustained")


def test_strip_fences_handles_raw_json() -> None:
    parsed = json.loads(_strip_fences(_VALID_BRIEF_JSON))
    assert parsed["recommendation"] == "Ship the eval script."


def test_strip_fences_handles_chatty_preamble() -> None:
    chatty = f"Sure! Here is your brief:\n{_VALID_BRIEF_JSON}\nLet me know."
    parsed = json.loads(_strip_fences(chatty))
    assert parsed["narrative"].startswith("Good")


def test_parse_brief_validates_into_pydantic() -> None:
    brief = _parse_brief(_VALID_BRIEF_JSON)
    assert isinstance(brief, StandupBrief)
    assert brief.has_attention_signal is False


def test_parse_brief_raises_on_garbage() -> None:
    with pytest.raises(BriefSynthesisError):
        _parse_brief("definitely not json at all")


def _settings_for(tmp_path: Path, name: str) -> Settings:
    return Settings(
        anthropic_api_key=None,
        nofari_db_path=tmp_path / f"{name}.db",
        nofari_repos=[],
    )


def _text_response(text: str) -> Any:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_synthesize_retries_once_and_succeeds(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path, "retry_ok")
    store = SignalStore(settings.nofari_db_path)
    await store.connect()

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(
        side_effect=[
            _text_response("this is not json at all"),
            _text_response(_VALID_BRIEF_JSON),
        ]
    )

    agent = LeadAgent(settings=settings, client=client, store=store)
    signal = Signal(
        source="codebase", kind="commit", title="x", ts=datetime.now(UTC)
    )
    brief = await agent.synthesize([signal])

    assert isinstance(brief, StandupBrief)
    assert client.messages.create.call_count == 2

    # Second call: cached, so no further client invocation.
    again = await agent.synthesize([signal])
    assert again.generated_at == brief.generated_at
    assert client.messages.create.call_count == 2

    await store.close()


@pytest.mark.asyncio
async def test_synthesize_raises_after_two_parse_failures(tmp_path: Path) -> None:
    settings = _settings_for(tmp_path, "retry_fail")
    store = SignalStore(settings.nofari_db_path)
    await store.connect()

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=_text_response("garbage"))

    agent = LeadAgent(settings=settings, client=client, store=store)
    signal = Signal(
        source="codebase", kind="commit", title="x", ts=datetime.now(UTC)
    )

    with pytest.raises(BriefSynthesisError):
        await agent.synthesize([signal])
    assert client.messages.create.call_count == 2

    await store.close()
