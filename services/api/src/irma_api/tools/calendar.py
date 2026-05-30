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
                detail="run `irma-api auth google` to grant calendar.events",
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
            raise ToolError(
                "calendar_auth_failed",
                detail=f"{exc}; if the token is stale or narrow-scoped, re-run `irma-api auth google`",
            ) from exc
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
            scopes=["https://www.googleapis.com/auth/calendar.events"],
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


class CreateCalendarEventTool:
    """Creates an event on the operator's primary Google Calendar."""

    spec = ToolSpec(
        name="create_calendar_event",
        description=(
            "Create an event on the operator's primary Google Calendar. "
            "Times must be RFC3339 (e.g. '2026-05-28T10:00:00Z'). "
            "Use this for scheduling focus blocks, reminders, or meetings."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start": {
                    "type": "string",
                    "description": "Start time, RFC3339 (e.g. 2026-05-28T10:00:00Z).",
                },
                "end": {
                    "type": "string",
                    "description": "End time, RFC3339. Must be strictly after start.",
                },
                "description": {"type": "string", "description": "Optional body text."},
                "location": {"type": "string", "description": "Optional location."},
            },
            "required": ["summary", "start", "end"],
            "additionalProperties": False,
        },
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def call(self, args: dict[str, Any]) -> str:
        if not self._has_credentials():
            raise ToolError(
                "calendar_unlinked",
                detail="run `irma-api auth google` to grant calendar.events",
            )

        summary = str(args.get("summary", "")).strip()
        start_raw = str(args.get("start", "")).strip()
        end_raw = str(args.get("end", "")).strip()
        if not summary or not start_raw or not end_raw:
            raise ToolError(
                "invalid_args",
                detail="summary, start, end are required",
            )
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ToolError(
                "invalid_args",
                detail=f"start/end must be RFC3339 timestamps: {exc}",
            ) from exc
        if start_dt.tzinfo is None or end_dt.tzinfo is None:
            raise ToolError(
                "invalid_args",
                detail="start/end must include a timezone (e.g. trailing 'Z' or '+HH:MM')",
            )
        if end_dt <= start_dt:
            raise ToolError("invalid_args", detail="end must be after start")

        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start_raw},
            "end": {"dateTime": end_raw},
        }
        description = str(args.get("description", "")).strip()
        if description:
            body["description"] = description
        location = str(args.get("location", "")).strip()
        if location:
            body["location"] = location

        client, user = self._build_creds()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential_jitter(initial=1, max=30),
                retry=retry_if_exception(_is_rate_limited),
                reraise=True,
            ):
                with attempt:
                    created = await self._insert_event(client, user, body)
        except (AuthError, RetryError) as exc:
            logger.warning("create_calendar_event.auth_failed", error=str(exc))
            raise ToolError(
                "calendar_auth_failed",
                detail=f"{exc}; if the token is stale or narrow-scoped, re-run `irma-api auth google`",
            ) from exc
        except HTTPError as exc:
            status = getattr(getattr(exc, "res", None), "status_code", None)
            logger.warning(
                "create_calendar_event.http_error", status=status, error=str(exc)
            )
            raise ToolError("calendar_http_error", detail=str(exc)) from exc

        link = str(created.get("htmlLink") or "")
        return f"created event {link}".strip()

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
            scopes=["https://www.googleapis.com/auth/calendar.events"],
        )
        user = UserCreds(
            refresh_token=s.google_oauth_refresh_token.get_secret_value(),
        )
        return client, user

    async def _insert_event(
        self,
        client: ClientCreds,
        user: UserCreds,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        async with Aiogoogle(user_creds=user, client_creds=client) as g:
            calendar = await g.discover("calendar", "v3")
            req = calendar.events.insert(calendarId="primary", json=body)
            resp = await g.as_user(req)
            return cast(dict[str, Any], resp)


# Module-level sanity: CreateCalendarEventTool conforms to Tool.
_create_calendar_event_tool_sanity: Tool = CreateCalendarEventTool.__new__(
    CreateCalendarEventTool
)
