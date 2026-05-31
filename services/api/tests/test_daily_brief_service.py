"""DailyBriefService.build(): context assembly, snapshot write, prose parse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from irma_api.agents.daily_brief import DailyBriefService
from irma_api.agents.llm import TextResult
from irma_api.config import Settings
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate, TaskStatus  # noqa: F401  (TaskStatus used indirectly)
from irma_api.runtime.state import StateBus
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.snapshot_repo import SnapshotRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore


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
    settings = Settings(_env_file=None, irma_db_path=Path("x"), irma_brief_lookahead_days=3)
    svc = DailyBriefService(
        settings=settings,
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
    settings = Settings(_env_file=None, irma_db_path=Path("x"))
    svc = DailyBriefService(
        settings=settings, llm=llm, store=store, observers=[], bus=StateBus(), calendar=None
    )
    brief = await svc.build()
    assert llm.calls == 2
    assert brief.narrative == "ok"
