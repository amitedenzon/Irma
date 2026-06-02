"""DailyBriefService.build(): context assembly, snapshot write, prose parse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from irma_api.agents.daily_brief import DailyBriefService
from irma_api.agents.llm import TextResult
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate, TaskStatus  # noqa: F401  (TaskStatus used indirectly)
from irma_api.runtime.state import StateBus
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.snapshot_repo import SnapshotRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore
from tests.conftest import make_profile_cache


class _FakeLLM:
    backend = "fake"
    model = "fake-1"

    def __init__(self) -> None:
        self.last_user: str = ""

    async def complete(self, *, system, messages, tools=None, max_tokens=1500, session_id=None):
        self.last_user = messages[-1].content
        return TextResult(
            text='{"narrative":"Morning.","recommendation":"Ship it.","conflicts":["x clashes y"]}'
        )


@pytest_asyncio.fixture
async def store(tmp_path: Path):
    s = SignalStore(tmp_path / "irma.db")
    await s.connect()
    try:
        yield s
    finally:
        await s.close()


@pytest.mark.asyncio
async def test_build_writes_snapshot_and_parses_prose(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    trepo = TaskRepo(store.connection)
    proj = await prepo.create(
        ProjectCreate(name="Alpha", goals=["g"], calendar_keywords=[], priority=1)
    )
    today = datetime.now(UTC).date()
    await trepo.create(
        TaskCreate(project_id=proj.id, title="due-soon", due_date=today + timedelta(days=1))
    )

    llm = _FakeLLM()
    svc = DailyBriefService(
        profile_cache=make_profile_cache(timezone="UTC", brief_lookahead_days=3),
        llm=llm,
        store=store,
        observers=[],
        bus=StateBus(),
        calendar=None,
    )

    brief = await svc.build()

    assert brief.narrative == "Morning."
    assert brief.recommendation == "Ship it."
    assert brief.conflicts == ["x clashes y"]
    assert any(it.title == "due-soon" for it in brief.lookahead_tasks)
    snap = await SnapshotRepo(store.connection).get(today)
    assert snap is not None
    assert proj.id in snap.per_project_counts
    assert brief.has_baseline is False
    assert any(p.project_name == "Alpha" for p in brief.progress)


@pytest.mark.asyncio
async def test_build_for_date_targets_that_delivery_day(store: SignalStore) -> None:
    """build(for_date=X) scopes focus/lookahead to X, not today — so a brief
    generated tonight describes tomorrow morning."""
    prepo = ProjectRepo(store.connection)
    trepo = TaskRepo(store.connection)
    proj = await prepo.create(
        ProjectCreate(name="Alpha", goals=["g"], calendar_keywords=[], priority=1)
    )
    today = datetime.now(UTC).date()
    target = today + timedelta(days=1)
    await trepo.create(TaskCreate(project_id=proj.id, title="due-on-target", due_date=target))
    await trepo.create(
        TaskCreate(project_id=proj.id, title="due-after-target", due_date=target + timedelta(days=1))
    )

    svc = DailyBriefService(
        profile_cache=make_profile_cache(timezone="UTC", brief_lookahead_days=3),
        llm=_FakeLLM(),
        store=store,
        observers=[],
        bus=StateBus(),
        calendar=None,
    )
    brief = await svc.build(for_date=target)

    # Due exactly on the delivery day → today's focus (due_date <= for_date).
    assert any(f.title == "due-on-target" for f in brief.today_focus)
    # Due the day after → lookahead, not focus.
    assert any(it.title == "due-after-target" for it in brief.lookahead_tasks)
    assert all(f.title != "due-after-target" for f in brief.today_focus)
    # The snapshot is written under the delivery date, not today.
    assert await SnapshotRepo(store.connection).get(target) is not None


@pytest.mark.asyncio
async def test_prepare_skips_llm_and_snapshot_and_fingerprint_tracks_state(
    store: SignalStore,
) -> None:
    prepo = ProjectRepo(store.connection)
    trepo = TaskRepo(store.connection)
    proj = await prepo.create(
        ProjectCreate(name="Alpha", goals=["g"], calendar_keywords=[], priority=1)
    )
    today = datetime.now(UTC).date()

    class _CountingLLM:
        backend = "fake"
        model = "fake-1"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *, system, messages, tools=None, max_tokens=1500, session_id=None):
            self.calls += 1
            return TextResult(text='{"narrative":"x","recommendation":"y","conflicts":[]}')

    llm = _CountingLLM()
    svc = DailyBriefService(
        profile_cache=make_profile_cache(timezone="UTC", brief_lookahead_days=3),
        llm=llm,
        store=store,
        observers=[],
        bus=StateBus(),
        calendar=None,
    )

    fp1, _ = await svc.prepare(today)
    assert llm.calls == 0  # no synthesis during prepare
    assert await SnapshotRepo(store.connection).get(today) is None  # no write during prepare

    fp2, _ = await svc.prepare(today)
    assert fp2 == fp1  # identical state → stable fingerprint

    await trepo.create(TaskCreate(project_id=proj.id, title="new", due_date=today))
    fp3, _ = await svc.prepare(today)
    assert fp3 != fp1  # state changed → fingerprint changes


@pytest.mark.asyncio
async def test_build_retries_once_on_bad_json(store: SignalStore) -> None:
    class _FlakyLLM:
        backend = "fake"
        model = "fake-1"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *, system, messages, tools=None, max_tokens=1500, session_id=None):
            self.calls += 1
            if self.calls == 1:
                return TextResult(text="not json at all")
            return TextResult(text='{"narrative":"ok","recommendation":"go","conflicts":[]}')

    llm = _FlakyLLM()
    svc = DailyBriefService(
        profile_cache=make_profile_cache(),
        llm=llm,
        store=store,
        observers=[],
        bus=StateBus(),
        calendar=None,
    )
    brief = await svc.build()
    assert llm.calls == 2
    assert brief.narrative == "ok"


@pytest.mark.asyncio
async def test_owner_context_injected_in_system_prompt(store: SignalStore) -> None:
    """build() injects owner_name/owner_role from the profile into the system prompt."""
    captured_system: list[str] = []

    class _CaptureLLM:
        backend = "fake"
        model = "fake-1"

        async def complete(self, *, system, messages, tools=None, max_tokens=1500, session_id=None):
            captured_system.append(system)
            return TextResult(
                text='{"narrative":"hi","recommendation":"go","conflicts":[]}'
            )

    cache = make_profile_cache(owner_name="Amit", owner_role="AI Researcher")
    svc = DailyBriefService(
        profile_cache=cache,
        llm=_CaptureLLM(),
        store=store,
        observers=[],
        bus=StateBus(),
        calendar=None,
    )
    await svc.build()

    assert len(captured_system) >= 1
    full_system = captured_system[0]
    assert "Amit" in full_system
    assert "AI Researcher" in full_system
