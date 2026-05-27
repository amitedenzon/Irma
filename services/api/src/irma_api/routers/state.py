"""AgentState introspection + SSE stream.

Phase 2 ships the `/state` snapshot endpoint; Phase 3 adds the `/stream`
SSE endpoint that drives the reactive sprite.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from irma_api.runtime.state import AgentState, StateBus

router = APIRouter(tags=["state"])

KEEPALIVE_SECONDS = 15


@router.get("/state")
async def current_state(request: Request) -> dict[str, str]:
    bus: StateBus = request.app.state.bus
    return {"state": bus.current.value}


@router.get("/stream")
async def stream_state(request: Request) -> StreamingResponse:
    bus: StateBus = request.app.state.bus

    async def gen() -> AsyncIterator[bytes]:
        async with bus.subscribe() as queue:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    state: AgentState = await asyncio.wait_for(
                        queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                    yield f"event: state\ndata: {state.value}\n\n".encode()
                except TimeoutError:
                    yield b": keep-alive\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
