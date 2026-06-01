"""ResendSendTool: recipient lock, payload shape, retry surface, hot-reload."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from irma_api.config import Settings
from irma_api.models.profile import Profile
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.tools.base import ToolError
from irma_api.tools.resend import ResendSendTool


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "resend_api_key": "re_test_key",
        "resend_from_email": "onboarding@resend.dev",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def _profile(**overrides: Any) -> Profile:
    defaults: dict[str, Any] = {
        "owner_email": "amit@example.com",
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Profile(**defaults)


def _loaded_cache(profile: Profile | None = None) -> ProfileCache:
    """Return a ProfileCache whose .current is already set (no DB needed)."""
    cache = ProfileCache.__new__(ProfileCache)
    cache._repo = MagicMock()  # type: ignore[attr-defined]
    cache._profile = profile or _profile()
    return cache


def _tool(**setting_overrides: Any) -> ResendSendTool:
    return ResendSendTool(_settings(**setting_overrides), _loaded_cache())


@pytest.mark.asyncio
async def test_spec_only_exposes_subject_and_body() -> None:
    tool = _tool()
    schema = tool.spec.input_schema
    assert set(schema["properties"].keys()) == {"subject", "body"}
    assert set(schema["required"]) == {"subject", "body"}
    # No `to` field anywhere — it must not be discoverable from the spec.
    assert "to" not in schema["properties"]


@pytest.mark.asyncio
async def test_send_posts_locked_recipient() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "msg_abc123"})

    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails").mock(side_effect=handler)
        result = await _tool().call({"subject": "hello", "body": "world"})

    assert result == "sent (message id msg_abc123)"
    assert captured["body"]["to"] == ["amit@example.com"]
    assert captured["body"]["from"] == "onboarding@resend.dev"
    assert captured["body"]["subject"] == "hello"
    assert captured["body"]["text"] == "world"
    assert captured["auth"] == "Bearer re_test_key"


@pytest.mark.asyncio
async def test_to_field_in_args_is_silently_dropped() -> None:
    """LLM cannot redirect the email by smuggling a `to` argument."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "x"})

    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails").mock(side_effect=handler)
        await _tool().call({"subject": "s", "body": "b", "to": "attacker@evil.com"})

    assert captured["body"]["to"] == ["amit@example.com"]


@pytest.mark.asyncio
async def test_missing_api_key_raises_unlinked() -> None:
    tool = ResendSendTool(_settings(resend_api_key=None), _loaded_cache())
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"subject": "s", "body": "b"})
    assert exc_info.value.code == "resend_unlinked"


@pytest.mark.asyncio
async def test_missing_user_email_raises_misconfigured() -> None:
    """profile.owner_email=None at call time → user_email_unset."""
    cache = _loaded_cache(_profile(owner_email=None))
    tool = ResendSendTool(_settings(), cache)
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"subject": "s", "body": "b"})
    assert exc_info.value.code == "user_email_unset"


@pytest.mark.asyncio
async def test_empty_subject_or_body_is_rejected() -> None:
    with pytest.raises(ToolError) as exc_info:
        await _tool().call({"subject": "  ", "body": "x"})
    assert exc_info.value.code == "invalid_args"


@pytest.mark.asyncio
async def test_4xx_response_raises_resend_failed_without_retrying() -> None:
    """4xx is a fail-fast — the LLM's payload is bad, not the transport."""
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(422, json={"message": "invalid from"})

    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails").mock(side_effect=handler)
        with pytest.raises(ToolError) as exc_info:
            await _tool().call({"subject": "s", "body": "b"})
    assert exc_info.value.code == "resend_failed"
    assert calls == 1


@pytest.mark.asyncio
async def test_429_then_success_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make tenacity's exponential jitter sleep be a no-op.
    import irma_api.tools.resend as resend_mod

    async def _no_sleep(_self: Any) -> None:
        return None

    monkeypatch.setattr(
        resend_mod.AsyncRetrying, "sleep", _no_sleep, raising=False
    )

    responses = iter([
        httpx.Response(429, json={"message": "slow down"}),
        httpx.Response(200, json={"id": "msg_after_retry"}),
    ])

    def handler(_request: httpx.Request) -> httpx.Response:
        return next(responses)

    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails").mock(side_effect=handler)
        result = await _tool().call({"subject": "s", "body": "b"})
    assert result == "sent (message id msg_after_retry)"


@pytest.mark.asyncio
async def test_hot_reload_recipient_from_profile_cache() -> None:
    """Changing the profile email in the cache is reflected on the next send."""
    cache = _loaded_cache(_profile(owner_email="first@example.com"))
    tool = ResendSendTool(_settings(), cache)

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body["to"][0])
        return httpx.Response(200, json={"id": "x"})

    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails").mock(side_effect=handler)

        # First send — uses initial profile email
        await tool.call({"subject": "s1", "body": "b1"})
        assert calls[-1] == "first@example.com"

        # Hot-swap the profile in the cache (simulates a PATCH /profile)
        updated = _profile(owner_email="second@example.com")
        cache.set(updated)

        # Second send — must pick up the new email without reconstructing the tool
        await tool.call({"subject": "s2", "body": "b2"})
        assert calls[-1] == "second@example.com"

    assert len(calls) == 2
