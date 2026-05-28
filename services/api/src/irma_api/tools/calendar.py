"""Google Calendar `read_calendar` exposed as a read-only Tool.

Reuses the same OAuth-2 + aiogoogle path as :class:`TimeAgent`, but as an
LLM-callable tool: the model can pull events on demand from inside /chat
(typically to compose a summary it will then send via ``send_email``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from aiogoogle import Aiogoogle  # type: ignore[attr-defined]
from aiogoogle.auth.creds import ClientCreds, UserCreds
from aiogoogle.excs import AuthError, HTTPError
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

_MAX_EVENTS = 50
_DEFAULT_DAYS = 1
_MAX_DAYS = 14


def _is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        status: int | None = getattr(getattr(exc, "res", None), "status_code", None)
        if status is None:
            return False
        return bool(status == 429 or 500 <= status < 600)
    return False


class ReadCalendarTool:
    """Fetches the operator's primary-calendar events for the next N days."""

    spec = ToolSpec(
        name="read_calendar",
        description=(
            "Read upcoming events from the operator's primary Google Calendar "
            "starting now. Returns a plain-text summary, one event per line. "
            "Use this to answer questions about the operator's schedule or to "
            "compose a daily-agenda email."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": _MAX_DAYS,
                    "description": (
                        f"Look-ahead window in days, 1..{_MAX_DAYS}. "
                        "1 = next 24 hours from now (the usual 'today' meaning)."
                    ),
                },
            },
            "additionalProperties": False,
        },
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def call(self, args: dict[str, Any]) -> str:
        if not self._has_credentials():
            raise ToolError(
                "calendar_unlinked",
                detail="run `irma-api auth google` to grant calendar.readonly",
            )

        days = int(args.get("days") or _DEFAULT_DAYS)
        days = max(1, min(_MAX_DAYS, days))

        client, user = self._build_creds()
        now = datetime.now(UTC)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential_jitter(initial=1, max=30),
                retry=retry_if_exception(_is_rate_limited),
                reraise=True,
            ):
                with attempt:
                    events = await self._fetch_events(client, user, time_min, time_max)
        except (AuthError, RetryError) as exc:
            logger.warning("read_calendar.auth_failed", error=str(exc))
            raise ToolError("calendar_auth_failed", detail=str(exc)) from exc
        except HTTPError as exc:
            status = getattr(getattr(exc, "res", None), "status_code", None)
            logger.warning("read_calendar.http_error", status=status, error=str(exc))
            raise ToolError("calendar_http_error", detail=str(exc)) from exc

        if not events:
            return f"No events in the next {days} day(s)."
        lines = [f"Calendar events for the next {days} day(s):"]
        lines.extend(self._format_event(e) for e in events if self._has_start(e))
        return "\n".join(lines)

    # --- internals -----------------------------------------------------------

    def _has_credentials(self) -> bool:
        s = self._settings
        return all(
            v is not None
            for v in (
                s.google_oauth_client_id,
                s.google_oauth_client_secret,
                s.google_oauth_refresh_token,
            )
        )

    def _build_creds(self) -> tuple[ClientCreds, UserCreds]:
        s = self._settings
        assert s.google_oauth_client_id is not None
        assert s.google_oauth_client_secret is not None
        assert s.google_oauth_refresh_token is not None
        client = ClientCreds(
            client_id=s.google_oauth_client_id.get_secret_value(),
            client_secret=s.google_oauth_client_secret.get_secret_value(),
            scopes=["https://www.googleapis.com/auth/calendar.readonly"],
        )
        user = UserCreds(
            refresh_token=s.google_oauth_refresh_token.get_secret_value(),
        )
        return client, user

    async def _fetch_events(
        self,
        client: ClientCreds,
        user: UserCreds,
        time_min: str,
        time_max: str,
    ) -> list[dict[str, Any]]:
        async with Aiogoogle(user_creds=user, client_creds=client) as g:
            calendar = await g.discover("calendar", "v3")
            req = calendar.events.list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=_MAX_EVENTS,
            )
            resp = await g.as_user(req)
            items = cast(dict[str, Any], resp).get("items", [])
            return cast(list[dict[str, Any]], items)

    @staticmethod
    def _has_start(event: dict[str, Any]) -> bool:
        start = event.get("start") or {}
        return bool(start.get("dateTime") or start.get("date"))

    @staticmethod
    def _format_event(event: dict[str, Any]) -> str:
        start = event.get("start") or {}
        end = event.get("end") or {}
        raw_start = str(start.get("dateTime") or start.get("date") or "")
        raw_end = str(end.get("dateTime") or end.get("date") or "")
        title = str(event.get("summary") or "(no title)")
        location = str(event.get("location") or "").strip()
        when = f"{raw_start} → {raw_end}" if raw_end else raw_start
        loc_part = f"  [{location}]" if location else ""
        return f"- {when}  {title}{loc_part}"


# Module-level sanity: ReadCalendarTool conforms to Tool.
_: Tool = ReadCalendarTool.__new__(ReadCalendarTool)
