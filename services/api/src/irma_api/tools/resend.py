"""Resend ``send_email`` exposed as a recipient-locked Tool.

Why locked: the tool is invoked by the LLM during /chat. A prompt-injection
payload riding in a calendar event description could otherwise convince the
model to email arbitrary recipients. The To: header is set server-side from
settings and the tool's args schema does not advertise a `to` field.
"""

from __future__ import annotations

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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def call(self, args: dict[str, Any]) -> str:
        if self._settings.irma_user_email is None:
            raise ToolError(
                "user_email_unset",
                detail="set IRMA_USER_EMAIL before enabling send_email",
            )
        if self._settings.resend_api_key is None:
            raise ToolError(
                "resend_unlinked",
                detail="set RESEND_API_KEY in .env",
            )

        subject = str(args.get("subject", "")).strip()
        body = str(args.get("body", ""))
        if not subject or not body:
            raise ToolError(
                "invalid_args",
                detail="both `subject` and `body` are required",
            )

        payload = {
            "from": self._settings.resend_from_email,
            "to": [self._settings.irma_user_email],
            "subject": subject,
            "text": body,
        }
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

        message_id = str(response.get("id", "?"))
        return f"sent (message id {message_id})"

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
