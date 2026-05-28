"""Installed-app OAuth bootstrap for Google APIs.

Runs locally: opens the system browser to Google's consent screen, captures
the authorization code on a loopback HTTP redirect, and exchanges it for a
refresh token. The caller is responsible for persisting the result (e.g.
writing it to ``.env``).

Scopes are read-only Calendar access — Irma's TimeAgent consumes events as
a passive data stream, never modifies them, and never reads mail.
"""

from __future__ import annotations

import http.server
import secrets
import socket
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass
from typing import Any

import httpx

SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.readonly",
)

_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class OAuthCancelled(RuntimeError):
    """Raised when the user denies consent or the token exchange fails."""


@dataclass(frozen=True)
class OAuthResult:
    refresh_token: str
    access_token: str | None


def build_auth_uri(*, client_id: str, redirect_uri: str, state: str) -> str:
    """URL-encode the Google OAuth consent screen target."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",            # force a refresh_token on every grant
        "state": state,
    }
    return f"{_AUTH_URI}?{urllib.parse.urlencode(params)}"


async def exchange_code_for_refresh_token(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> str:
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(_TOKEN_URI, data=payload)
    body: dict[str, Any] = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        raise OAuthCancelled(
            f"token exchange failed: {body.get('error', resp.status_code)}"
        )
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str):
        raise OAuthCancelled(
            "no refresh_token in response — revoke the previous grant in "
            "https://myaccount.google.com/permissions and retry"
        )
    return refresh_token


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_callback_server(port: int, expected_state: str) -> dict[str, str]:
    """Block until the browser hits ``GET /callback?code=...``. Returns the params."""
    captured: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            captured["code"] = (qs.get("code") or [""])[0]
            captured["state"] = (qs.get("state") or [""])[0]
            captured["error"] = (qs.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Irma: you can close this tab.\n")

        def log_message(self, *_args: Any) -> None:
            return  # silence the BaseHTTPServer access log

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    try:
        server.handle_request()
    finally:
        server.server_close()

    if captured.get("state") != expected_state:
        raise OAuthCancelled("state mismatch — possible CSRF, aborting")
    if captured.get("error"):
        raise OAuthCancelled(f"consent denied: {captured['error']}")
    if not captured.get("code"):
        raise OAuthCancelled("no authorization code in callback")
    return captured


async def run_installed_app_flow(
    *,
    client_id: str,
    client_secret: str,
    open_browser: bool = True,
) -> OAuthResult:
    """Drive the full installed-app flow and return the refresh token.

    The caller is responsible for prompting the user, writing ``.env``, etc.
    """
    port = _pick_free_port()
    redirect_uri = f"http://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)

    auth_uri = build_auth_uri(
        client_id=client_id, redirect_uri=redirect_uri, state=state
    )

    server_thread_result: dict[str, dict[str, str]] = {}

    def serve() -> None:
        server_thread_result["captured"] = _run_callback_server(port, state)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    if open_browser:
        webbrowser.open(auth_uri, new=1, autoraise=True)
    else:
        # Non-interactive callers print the URL and drive the callback themselves.
        print(f"Open this URL to grant access:\n  {auth_uri}")

    thread.join()
    captured = server_thread_result.get("captured")
    if captured is None:
        raise OAuthCancelled("callback server exited without capturing a code")

    refresh_token = await exchange_code_for_refresh_token(
        client_id=client_id,
        client_secret=client_secret,
        code=captured["code"],
        redirect_uri=redirect_uri,
    )
    return OAuthResult(refresh_token=refresh_token, access_token=None)
