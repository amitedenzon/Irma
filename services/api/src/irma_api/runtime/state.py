"""AgentState bus — single-broadcaster, fan-out asyncio pub/sub.

Subscribers each own a bounded `asyncio.Queue`. On `put_nowait` failure (queue
full) we drop the oldest item to preserve liveness: a stuck SSE client must
never block the broadcaster, and stale state is worse than missed
intermediate transitions for a UI cue.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from enum import StrEnum

import structlog

logger = structlog.get_logger(__name__)


class AgentState(StrEnum):
    IDLE = "idle"
    OBSERVING = "observing"
    THINKING = "thinking"
    ALERT = "alert"


class StateBus:
    """Process-wide AgentState broadcaster."""

    def __init__(self, *, queue_size: int = 16) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[AgentState]] = set()
        self._current: AgentState = AgentState.IDLE
        self._lock = asyncio.Lock()

    @property
    def current(self) -> AgentState:
        return self._current

    async def publish(self, state: AgentState) -> None:
        async with self._lock:
            self._current = state
            for q in list(self._subscribers):
                try:
                    q.put_nowait(state)
                except asyncio.QueueFull:
                    # Drop the oldest pending state to keep the freshest one.
                    with suppress(asyncio.QueueEmpty):
                        _ = q.get_nowait()
                    try:
                        q.put_nowait(state)
                    except asyncio.QueueFull:  # pragma: no cover - extreme contention
                        logger.warning("statebus.queue_drop", state=state.value)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[AgentState]]:
        """Async context manager that yields a per-subscriber queue."""
        q: asyncio.Queue[AgentState] = asyncio.Queue(maxsize=self._queue_size)
        # Push current state so a fresh subscriber learns the world immediately.
        q.put_nowait(self._current)
        async with self._lock:
            self._subscribers.add(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subscribers.discard(q)
