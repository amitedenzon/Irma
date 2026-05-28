"""LeadAgent: horizon dispatch, context window, cache hit/miss, retry."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio

from irma_api.agents.lead_agent import LeadAgent
from irma_api.agents.llm import ChatTurn, CompleteResult, TextResult
from irma_api.tools.base import ToolSpec
from irma_api.config import Settings
from irma_api.models.brief import Horizon
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore


class FakeLLM:
    """LLMClient stand-in with scripted responses + replay log."""

    backend = "fake"
    model = "fake-1"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, Sequence[ChatTurn]]] = []

    async def complete(
        self,
        *,
        system: str,
        messages: Sequence[ChatTurn],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
    ) -> CompleteResult:
        self.calls.append((system, list(messages)))
        return TextResult(text=self._responses.pop(0))


def _brief_json(horizon: str) -> str:
    return (
        f'{{"horizon":"{horizon}","generated_at":"2026-05-27T12:00:00+00:00",'
        '"focus":[],"project_status":[],"conflicts":[],'
        '"recommendation":"ok","narrative":""}'
    )


@pytest_asyncio.fixture
async def seeded_store(tmp_path: Path) -> SignalStore:
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    prepo = ProjectRepo(store.connection)
    trepo = TaskRepo(store.connection)
    p = await prepo.create(
        ProjectCreate(name="Thesis", goals=["Submit"], target_date=date(2026, 7, 15))
    )
    await trepo.create(TaskCreate(project_id=p.id, title="today", scheduled_for=date(2026, 5, 27)))
    await trepo.create(
        TaskCreate(project_id=p.id, title="next-week", scheduled_for=date(2026, 6, 3))
    )
    return store


def _settings() -> Settings:
    return Settings(
        irma_db_path=Path("/tmp/irma.db"),
        anthropic_api_key=None,
        anthropic_model="x",
    )


@pytest.mark.asyncio
async def test_synthesize_day_returns_parsed_brief(
    seeded_store: SignalStore,
) -> None:
    llm = FakeLLM([_brief_json("day")])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    brief = await agent.synthesize("day")
    assert brief.horizon == "day"
    assert llm.calls and llm.calls[0][0]
    await seeded_store.close()


@pytest.mark.asyncio
async def test_cache_hit_skips_llm(seeded_store: SignalStore) -> None:
    llm = FakeLLM([_brief_json("day")])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    first = await agent.synthesize("day")
    second = await agent.synthesize("day")
    assert first == second
    assert len(llm.calls) == 1
    await seeded_store.close()


@pytest.mark.asyncio
async def test_cache_invalidates_on_task_change(
    seeded_store: SignalStore,
) -> None:
    llm = FakeLLM([_brief_json("day"), _brief_json("day")])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    await agent.synthesize("day")
    trepo = TaskRepo(seeded_store.connection)
    fresh = (await trepo.list())[0]
    from irma_api.models.task import TaskStatus, TaskUpdate

    await trepo.update(fresh.id, TaskUpdate(status=TaskStatus.DONE))
    await agent.synthesize("day")
    assert len(llm.calls) == 2
    await seeded_store.close()


@pytest.mark.asyncio
async def test_parse_failure_retries_once(seeded_store: SignalStore) -> None:
    llm = FakeLLM(["not-json", _brief_json("day")])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    b = await agent.synthesize("day")
    assert b.horizon == "day"
    assert len(llm.calls) == 2
    await seeded_store.close()


@pytest.mark.asyncio
async def test_parse_failure_twice_raises(seeded_store: SignalStore) -> None:
    llm = FakeLLM(["not-json", "still-not-json"])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    from irma_api.agents.lead_agent import BriefSynthesisError

    with pytest.raises(BriefSynthesisError):
        await agent.synthesize("day")
    await seeded_store.close()


@pytest.mark.asyncio
async def test_empty_context_short_circuits(tmp_path: Path) -> None:
    """No projects → return stub brief without calling the LLM."""
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    llm = FakeLLM([])
    agent = LeadAgent(settings=_settings(), llm=llm, store=store)
    b = await agent.synthesize("day")
    assert b.recommendation
    assert llm.calls == []
    await store.close()


@pytest.mark.asyncio
async def test_horizon_appears_in_user_message(
    seeded_store: SignalStore,
) -> None:
    """The composed prompt mentions the requested horizon."""
    llm = FakeLLM([_brief_json("week")])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    await agent.synthesize("week")
    user_msg = llm.calls[0][1][0].content
    assert "week" in user_msg
    await seeded_store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("horizon", ["day", "week", "month", "all"])
async def test_all_four_horizons_dispatch(seeded_store: SignalStore, horizon: Horizon) -> None:
    llm = FakeLLM([_brief_json(horizon)])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    b = await agent.synthesize(horizon)
    assert b.horizon == horizon
    await seeded_store.close()
