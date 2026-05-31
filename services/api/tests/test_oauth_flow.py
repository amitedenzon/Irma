"""Installed-app OAuth flow: URL build + token exchange (browser/server mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from irma_api.auth.google_oauth import (
    SCOPES,
    OAuthCancelled,
    build_auth_uri,
    exchange_code_for_refresh_token,
)


def test_auth_uri_includes_required_scopes_and_loopback_redirect() -> None:
    uri = build_auth_uri(
        client_id="cid.apps.googleusercontent.com",
        redirect_uri="http://localhost:53111/callback",
        state="abc",
    )
    assert "https://accounts.google.com/o/oauth2/v2/auth" in uri
    assert "client_id=cid.apps.googleusercontent.com" in uri
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A53111%2Fcallback" in uri
    for scope in SCOPES:
        assert scope.replace(":", "%3A").replace("/", "%2F") in uri
    assert "access_type=offline" in uri
    assert "prompt=consent" in uri
    assert "state=abc" in uri


def test_scopes_are_calendar_events_only() -> None:
    """calendar.events is granted — covers both reads and writes."""
    assert SCOPES == (
        "https://www.googleapis.com/auth/calendar.events",
    )


@pytest.mark.asyncio
async def test_exchange_code_returns_refresh_token() -> None:
    fake_response = httpx.Response(
        status_code=200,
        json={
            "access_token": "ya29.xxx",
            "refresh_token": "1//rt-here",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )
    async_mock = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=async_mock):
        token = await exchange_code_for_refresh_token(
            client_id="cid",
            client_secret="secret",
            code="auth-code",
            redirect_uri="http://localhost:53111/callback",
        )
    assert token == "1//rt-here"


@pytest.mark.asyncio
async def test_exchange_code_raises_on_non_2xx() -> None:
    fake_response = httpx.Response(
        status_code=400, json={"error": "invalid_grant"}
    )
    async_mock = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=async_mock):
        with pytest.raises(OAuthCancelled) as exc_info:
            await exchange_code_for_refresh_token(
                client_id="cid",
                client_secret="secret",
                code="bad",
                redirect_uri="http://localhost:53111/callback",
            )
    assert "invalid_grant" in str(exc_info.value)


@pytest.mark.asyncio
async def test_exchange_code_raises_when_no_refresh_token() -> None:
    fake_response = httpx.Response(
        status_code=200,
        json={"access_token": "ya29.xxx", "expires_in": 3600},
    )
    async_mock = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient.post", new=async_mock):
        with pytest.raises(OAuthCancelled) as exc_info:
            await exchange_code_for_refresh_token(
                client_id="cid",
                client_secret="secret",
                code="x",
                redirect_uri="http://localhost:53111/callback",
            )
    assert "no refresh_token" in str(exc_info.value)
