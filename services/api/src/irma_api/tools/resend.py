"""Resend ``send_email`` exposed as a recipient-locked Tool.

Why locked: the tool is invoked by the LLM during /chat. A prompt-injection
payload riding in a calendar event description could otherwise convince the
model to email arbitrary recipients. The To: header is set server-side from
the owner profile and the tool's args schema does not advertise a `to` field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from irma_api.config import Settings
from irma_api.runtime.profile_cache import ProfileCache
from irma_api.tools.base import Tool, ToolError, ToolSpec

logger = structlog.get_logger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


class _ResendHTTPError(RuntimeError):
    """Wraps a non-2xx Resend response so tenacity can decide whether to retry."""

    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"resend status={status_code}: {body[:200]}")
        self.status_code = status_code
        self.body = body


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, _ResendHTTPError):
        return exc.status_code == 429 or 500 <= exc.status_code < 600
    if isinstance(exc, httpx.TransportError):
        return True
    return False


class ResendSendTool:
    """Sends a plain-text email from the configured From address to the operator."""

    spec = ToolSpec(
        name="send_email",
        description=(
            "Send a plain-text email to the operator's own inbox. "
            "Use for self-reminders, notes, or surfacing important state. "
            "The recipient is fixed; you cannot specify one."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Short subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "Plain-text body of the email.",
                },
            },
            "required": ["subject", "body"],
            "additionalProperties": False,
        },
    )

    def __init__(self, settings: Settings, profile_cache: ProfileCache) -> None:
        self._settings = settings
        self._profile_cache = profile_cache

    def _recipient(self) -> str:
        """Resolve the locked recipient and assert Resend is configured.

        Order matters: a missing recipient reports ``user_email_unset`` even
        when the key is also absent (mirrors the tool's documented behaviour).
        """
        recipient = self._profile_cache.current.owner_email
        if recipient is None:
            raise ToolError(
                "user_email_unset",
                detail="set IRMA_USER_EMAIL before enabling send_email",
            )
        if self._settings.resend_api_key is None:
            raise ToolError(
                "resend_unlinked",
                detail="set RESEND_API_KEY in .env",
            )
        return recipient

    async def call(self, args: dict[str, Any]) -> str:
        recipient = self._recipient()

        subject = str(args.get("subject", "")).strip()
        body = str(args.get("body", ""))
        if not subject or not body:
            raise ToolError(
                "invalid_args",
                detail="both `subject` and `body` are required",
            )

        from irma_api.agents.email_render import render_simple_html  # local import: avoids circular

        html_body = str(args.get("html", "")).strip()
        if not html_body:
            html_body = render_simple_html(subject, body)

        payload: dict[str, Any] = {
            "from": self._settings.resend_from_email,
            "to": [recipient],
            "subject": subject,
            "text": body,
            "html": html_body,
        }
        response = await self._send(payload)
        return f"sent (message id {response.get('id', '?')})"

    async def schedule_email(
        self, *, subject: str, body: str, html: str, scheduled_at: datetime
    ) -> str:
        """Queue an email for future delivery via Resend's ``scheduled_at``.

        Unlike :meth:`call` (the LLM-facing tool) this is an internal sender
        used by the daily-brief queue: it takes pre-rendered HTML + text and a
        delivery time, and returns the bare Resend message id so the caller can
        later cancel/replace it.
        """
        recipient = self._recipient()
        payload: dict[str, Any] = {
            "from": self._settings.resend_from_email,
            "to": [recipient],
            "subject": subject,
            "text": body,
            "html": html,
            "scheduled_at": scheduled_at.isoformat(),
        }
        response = await self._send(payload)
        return str(response.get("id", ""))

    async def cancel_email(self, email_id: str) -> None:
        """Cancel a previously-scheduled email. Raises if Resend rejects it.

        A 4xx here typically means the email already sent (too late to cancel);
        the caller is expected to catch and continue.
        """
        if self._settings.resend_api_key is None:
            raise ToolError("resend_unlinked", detail="set RESEND_API_KEY in .env")
        headers = {
            "Authorization": f"Bearer {self._settings.resend_api_key.get_secret_value()}",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{_RESEND_URL}/{email_id}/cancel", headers=headers)
        if resp.status_code >= 400:
            logger.warning("resend.cancel_failed", status=resp.status_code, email_id=email_id)
            raise ToolError(
                "resend_cancel_failed",
                detail=f"status={resp.status_code}: {resp.text[:200]}",
            )

    async def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential_jitter(initial=1, max=30),
                retry=retry_if_exception(_is_retryable),
                reraise=True,
            ):
                with attempt:
                    response = await self._post(payload)
        except RetryError as exc:
            logger.warning("resend.retry_exhausted", error=str(exc))
            raise ToolError("resend_retry_exhausted", detail=str(exc)) from exc
        except _ResendHTTPError as exc:
            logger.warning("resend.http_error", status=exc.status_code, body=exc.body[:200])
            raise ToolError("resend_failed", detail=str(exc)) from exc
        return response

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self._settings.resend_api_key is not None  # checked by call()
        headers = {
            "Authorization": f"Bearer {self._settings.resend_api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_RESEND_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            raise _ResendHTTPError(resp.status_code, resp.text)
        try:
            data = resp.json()
        except ValueError:
            return {}
        return dict(data) if isinstance(data, dict) else {}


# Module-level sanity: ResendSendTool conforms to Tool.
_: Tool = ResendSendTool.__new__(ResendSendTool)
