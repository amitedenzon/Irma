"""StateBus fan-out + drop-oldest backpressure."""

from __future__ import annotations

import asyncio

import pytest

from irma_api.runtime.state import AgentState, StateBus


@pytest.mark.asyncio
async def test_fan_out_to_multiple_subscribers() -> None:
    bus = StateBus()

    async def collect(sub_id: int) -> list[AgentState]:
        seen: list[AgentState] = []
        async with bus.subscribe() as q:
            # initial snapshot
            seen.append(await q.get())
            # two more transitions
            seen.append(await q.get())
            seen.append(await q.get())
        return seen

    task_a = asyncio.create_task(collect(0))
    task_b = asyncio.create_task(collect(1))
    await asyncio.sleep(0)  # let subscribers register

    await bus.publish(AgentState.OBSERVING)
    await bus.publish(AgentState.ALERT)

    a, b = await asyncio.gather(task_a, task_b)
    assert a == [AgentState.IDLE, AgentState.OBSERVING, AgentState.ALERT]
    assert b == [AgentState.IDLE, AgentState.OBSERVING, AgentState.ALERT]


@pytest.mark.asyncio
async def test_drop_oldest_under_backpressure() -> None:
    bus = StateBus(queue_size=2)
    async with bus.subscribe() as q:
        # Subscriber starts with current state (IDLE) already enqueued.
        # Publish 4 more without draining → must not raise, must end on freshest.
        for state in (
            AgentState.OBSERVING,
            AgentState.THINKING,
            AgentState.ALERT,
            AgentState.IDLE,
        ):
            await bus.publish(state)

        drained: list[AgentState] = []
        while not q.empty():
            drained.append(q.get_nowait())

        assert drained, "subscriber must still receive items after backpressure"
        assert drained[-1] is AgentState.IDLE
        assert len(drained) <= 2
