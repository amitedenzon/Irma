"""Calendar observer — pulls the next 7 days of events from Google Calendar.

REST via `aiogoogle` (async). OAuth2 with a long-lived refresh token. Missing
credentials degrade gracefully: the observer returns `[]` and sets
`unlinked=True`; the runtime layer surfaces an `AgentState.alert` notice.
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
from irma_api.models.signal import Signal

logger = structlog.get_logger(__name__)

_MAX_EVENTS = 50
_HORIZON_DAYS = 7


def _is_rate_limited(exc: BaseException) -> bool:
    """Retry only on 429 (and 5xx, which are equivalent for backoff purposes)."""
    if isinstance(exc, HTTPError):
        status: int | None = getattr(getattr(exc, "res", None), "status_code", None)
        if status is None:
            return False
        return bool(status == 429 or 500 <= status < 600)
    return False


class TimeAgent:
    """Read-only Google Calendar observer."""

    name = "calendar"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.unlinked: bool = not self._has_credentials()

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
        # `_has_credentials` is the only caller path; secrets are guaranteed.
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

    async def collect(self) -> list[Signal]:
        if not self._has_credentials():
            self.unlinked = True
            logger.info("calendar.unlinked")
            return []

        client, user = self._build_creds()
        now = datetime.now(UTC)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=_HORIZON_DAYS)).isoformat()

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
            logger.warning("calendar.auth_failed", error=str(exc))
            self.unlinked = True
            return []
        except HTTPError as exc:
            status = getattr(getattr(exc, "res", None), "status_code", None)
            logger.warning("calendar.http_error", status=status, error=str(exc))
            return []

        self.unlinked = False
        return [self._to_signal(e) for e in events if self._has_start(e)]

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
    def _to_signal(event: dict[str, Any]) -> Signal:
        start = event.get("start") or {}
        end = event.get("end") or {}
        raw_start = start.get("dateTime") or start.get("date")
        try:
            ts = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(UTC)
        attendees = [a.get("email") for a in event.get("attendees", []) if isinstance(a, dict)]
        return Signal(
            source="calendar",
            kind="event",
            title=str(event.get("summary") or "(no title)"),
            detail=str(event.get("description") or "")[:1200],
            ts=ts,
            meta={
                "event_id": event.get("id"),
                "end": end.get("dateTime") or end.get("date"),
                "location": event.get("location"),
                "attendees": [a for a in attendees if a],
                "all_day": "date" in start and "dateTime" not in start,
            },
        )
