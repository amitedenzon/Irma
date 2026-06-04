"""ScheduledBriefQueue — keep the next morning's pretty brief queued at Resend.

The Mac is usually asleep at the brief hour, so we can't render the brief *at*
8am. Instead, whenever the backend is awake (startup + every refresh tick) we
render the brief for the *next* 8am and hand it to Resend's ``scheduled_at`` so
delivery happens server-side with the lid closed. Each render is for the
delivery morning (``for_date``), not the generation moment.

Re-queuing is deduped on an inputs fingerprint so we don't burn LLM tokens (or
churn the Resend API) when nothing changed. When the inputs *do* change we
cancel the previously-queued email and schedule a fresh one — so the 8am send
always reflects the last awake moment before the brief hour.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.email_render import render_daily_email, render_daily_email_html
from irma_api.models.daily_brief import DailyBrief
from irma_api.runtime.profile_cache import ProfileCache

logger = structlog.get_logger(__name__)


def next_brief_time(now: datetime, *, hour: int, minute: int = 0, timezone: str) -> datetime:
    """Return the next ``hour``:``minute`` in ``timezone`` strictly after ``now``.

    ``now`` may be in any timezone; it is converted into ``timezone`` first.
    """
    tz = ZoneInfo(timezone)
    local = now.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


class _Builder(Protocol):
    async def prepare(self, for_date: date) -> tuple[str, Any]:
        """Collect brief inputs for ``for_date`` (no LLM) → (fingerprint, inputs)."""
        ...

    async def render(self, inputs: Any, for_date: date) -> DailyBrief:
        """Synthesize + persist the brief from already-collected ``inputs``."""
        ...


class _ScheduledSender(Protocol):
    async def schedule_email(
        self, *, subject: str, body: str, html: str, scheduled_at: datetime
    ) -> str: ...

    async def cancel_email(self, email_id: str) -> None: ...


@dataclass
class QueuedBrief:
    """The brief email currently parked at Resend for a future morning."""

    target_date: date
    fingerprint: str
    email_id: str
    scheduled_at: str  # ISO 8601 delivery time — re-queued if the brief hour moves


class _StateStore(Protocol):
    def load(self) -> QueuedBrief | None: ...
    def save(self, state: QueuedBrief) -> None: ...
    def clear(self) -> None: ...


class BriefQueueStateStore:
    """Persists the currently-queued brief to a small JSON file beside the DB.

    Survives restarts so a reboot doesn't orphan (and then double-send) the
    email already parked at Resend. A missing or malformed file reads as "no
    queued brief" — the queue then schedules fresh.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> QueuedBrief | None:
        try:
            data = json.loads(self._path.read_text())
            return QueuedBrief(
                target_date=date.fromisoformat(str(data["target_date"])),
                fingerprint=str(data["fingerprint"]),
                email_id=str(data["email_id"]),
                scheduled_at=str(data["scheduled_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, state: QueuedBrief) -> None:
        payload = {
            "target_date": state.target_date.isoformat(),
            "fingerprint": state.fingerprint,
            "email_id": state.email_id,
            "scheduled_at": state.scheduled_at,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self._path)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


class ScheduledBriefQueue:
    def __init__(
        self,
        *,
        service: _Builder,
        sender: _ScheduledSender,
        state_store: _StateStore,
        profile_cache: ProfileCache,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service
        self._sender = sender
        self._state = state_store
        self._profile_cache = profile_cache
        self._now = now
        self._lock = asyncio.Lock()

    async def ensure_queued(self) -> dict[str, object]:
        """Render the next morning's brief and keep exactly one copy queued.

        Idempotent and safe to call on every refresh tick: it re-renders only
        when the inputs fingerprint changed for the current delivery day, in
        which case it cancels the stale queued email and schedules a fresh one.
        Serialized by a lock so overlapping ticks can't double-schedule.
        """
        async with self._lock:
            profile = self._profile_cache.current
            if not profile.daily_brief_enabled:
                prev = self._state.load()
                if prev is not None:
                    try:
                        await self._sender.cancel_email(prev.email_id)
                    except Exception as exc:
                        logger.warning(
                            "brief_queue.cancel_failed", email_id=prev.email_id, error=str(exc)
                        )
                    self._state.clear()
                return {"queued": False, "reason": "disabled"}

            target_dt = next_brief_time(
                self._now(), hour=profile.brief_hour, minute=profile.brief_minute,
                timezone=profile.timezone,
            )
            for_date = target_dt.date()
            target_iso = target_dt.isoformat()

            fingerprint, inputs = await self._service.prepare(for_date)
            prev = self._state.load()
            if (
                prev
                and prev.target_date == for_date
                and prev.fingerprint == fingerprint
                and prev.scheduled_at == target_iso
            ):
                return {"queued": False, "reason": "unchanged"}

            brief = await self._service.render(inputs, for_date)
            subject, text = render_daily_email(brief, for_date)
            html = render_daily_email_html(brief, for_date)

            # Replace only within the same delivery day: a prev email for an
            # earlier date has already fired and can't (shouldn't) be cancelled.
            # If the cancel fails we must NOT schedule a replacement — otherwise
            # both the stale and the fresh copy fire at the brief hour. Keep the
            # existing one and bail; the next tick retries the cancel.
            if prev is not None and prev.target_date == for_date:
                try:
                    await self._sender.cancel_email(prev.email_id)
                except Exception as exc:
                    logger.warning(
                        "brief_queue.cancel_failed_kept_existing",
                        email_id=prev.email_id,
                        error=str(exc),
                    )
                    return {"queued": False, "reason": "cancel_failed"}

            email_id = await self._sender.schedule_email(
                subject=subject, body=text, html=html, scheduled_at=target_dt
            )
            self._state.save(
                QueuedBrief(
                    target_date=for_date,
                    fingerprint=fingerprint,
                    email_id=email_id,
                    scheduled_at=target_iso,
                )
            )
            logger.info(
                "brief_queue.scheduled",
                target=for_date.isoformat(),
                at=target_dt.isoformat(),
                email_id=email_id,
            )
            return {"queued": True, "target_date": for_date.isoformat(), "email_id": email_id}
