"""ResendSendTool: recipient lock, payload shape, retry surface."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from irma_api.config import Settings
from irma_api.tools.base import ToolError
from irma_api.tools.resend import ResendSendTool


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "irma_user_email": "amit@example.com",
        "resend_api_key": "re_test_key",
        "resend_from_email": "onboarding@resend.dev",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.mark.asyncio
async def test_spec_only_exposes_subject_and_body() -> None:
    tool = ResendSendTool(_settings())
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
        result = await ResendSendTool(_settings()).call(
            {"subject": "hello", "body": "world"}
        )

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
        await ResendSendTool(_settings()).call(
            {"subject": "s", "body": "b", "to": "attacker@evil.com"}
        )

    assert captured["body"]["to"] == ["amit@example.com"]


@pytest.mark.asyncio
async def test_missing_api_key_raises_unlinked() -> None:
    tool = ResendSendTool(_settings(resend_api_key=None))
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"subject": "s", "body": "b"})
    assert exc_info.value.code == "resend_unlinked"


@pytest.mark.asyncio
async def test_missing_user_email_raises_misconfigured() -> None:
    tool = ResendSendTool(_settings(irma_user_email=None))
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"subject": "s", "body": "b"})
    assert exc_info.value.code == "user_email_unset"


@pytest.mark.asyncio
async def test_empty_subject_or_body_is_rejected() -> None:
    tool = ResendSendTool(_settings())
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"subject": "  ", "body": "x"})
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
            await ResendSendTool(_settings()).call(
                {"subject": "s", "body": "b"}
            )
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
        result = await ResendSendTool(_settings()).call(
            {"subject": "s", "body": "b"}
        )
    assert result == "sent (message id msg_after_retry)"
