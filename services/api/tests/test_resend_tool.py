"""ResendSendTool: recipient lock, payload shape, retry surface, hot-reload."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from irma_api.config import Settings
from irma_api.models.profile import Profile
from irma_api.tools.base import ToolError
from irma_api.tools.resend import ResendSendTool
from tests.conftest import make_profile_cache


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


def _tool(**setting_overrides: Any) -> ResendSendTool:
    return ResendSendTool(_settings(**setting_overrides), make_profile_cache(owner_email="amit@example.com"))


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
    tool = ResendSendTool(_settings(resend_api_key=None), make_profile_cache(owner_email="amit@example.com"))
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"subject": "s", "body": "b"})
    assert exc_info.value.code == "resend_unlinked"


@pytest.mark.asyncio
async def test_missing_user_email_raises_misconfigured() -> None:
    """profile.owner_email=None at call time → user_email_unset."""
    cache = make_profile_cache(profile=_profile(owner_email=None))
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
async def test_schedule_email_includes_scheduled_at_and_returns_id() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "msg_sched_1"})

    when = datetime(2026, 6, 2, 5, 0, tzinfo=UTC)
    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails").mock(side_effect=handler)
        email_id = await _tool().schedule_email(
            subject="Brief", body="text body", html="<p>html body</p>", scheduled_at=when
        )

    assert email_id == "msg_sched_1"
    assert captured["body"]["scheduled_at"] == when.isoformat()
    assert captured["body"]["to"] == ["amit@example.com"]
    assert captured["body"]["html"] == "<p>html body</p>"
    assert captured["body"]["text"] == "text body"


@pytest.mark.asyncio
async def test_cancel_email_posts_to_cancel_endpoint() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "msg_x", "object": "email"})

    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails/msg_x/cancel").mock(side_effect=handler)
        await _tool().cancel_email("msg_x")

    assert captured["auth"] == "Bearer re_test_key"


@pytest.mark.asyncio
async def test_cancel_email_raises_on_failure() -> None:
    async with respx.mock() as rmock:
        rmock.post("https://api.resend.com/emails/gone/cancel").mock(
            return_value=httpx.Response(404, json={"message": "not found"})
        )
        with pytest.raises(ToolError) as exc_info:
            await _tool().cancel_email("gone")
    assert exc_info.value.code == "resend_cancel_failed"


@pytest.mark.asyncio
async def test_hot_reload_recipient_from_profile_cache() -> None:
    """Changing the profile email in the cache is reflected on the next send."""
    cache = make_profile_cache(profile=_profile(owner_email="first@example.com"))
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
