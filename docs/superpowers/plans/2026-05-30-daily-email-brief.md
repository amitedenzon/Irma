# Daily Email Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-app Brief tab with an emailed daily brief — auto-sent at 08:00 Asia/Jerusalem, plus an on-demand "Brief" button — that reports per-project progress since the last brief and a 3-day lookahead of task deadlines and calendar events.

**Architecture:** A new `DailyBriefService` (backend) re-runs observers, gathers active projects/tasks, computes a per-project progress delta against a date-keyed `daily_snapshot` baseline, builds a 3-day lookahead from tasks ∪ Google Calendar, makes one Irma-voiced LLM call for prose, and writes today's snapshot. A `DailyBriefJob` wraps it with date-keyed idempotency; an APScheduler `CronTrigger(hour=8, tz=Asia/Jerusalem)` drives the morning send, and `POST /api/v1/brief/email` drives the on-demand send. The frontend drops the Brief tab and swaps the Refresh icon for a Brief button.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, APScheduler, pydantic v2, pytest-asyncio; React + TypeScript + Vite (Tauri).

**Working directory note:** All backend paths are relative to `services/api/`. Run all `pytest`/`ruff`/`mypy` from `services/api/` via `uv run`. All frontend paths are relative to `apps/desktop/`.

---

## Concurrency & Branch Safety (READ FIRST — non-negotiable)

This plan executes in a **shared, dirty working tree** on branch `feat/chat-tools-parity` where **another Claude may be actively working** (the "claude terminal panel" feature). `HEAD` moved during planning, and `apps/desktop/src/lib/icons.tsx` + `apps/desktop/src/main/settings/` are **untracked** working-tree files this plan depends on. Therefore:

1. **Do NOT switch, create, rebase, reset, or delete branches. Do NOT stash. Do NOT `git checkout`.** Moving `HEAD` in this shared worktree would yank it out from under a concurrent agent. Work in place on the current branch.
2. **Never `git add -A`, `git add .`, or `git commit -a`.** Stage only the explicit per-task file paths listed in each commit step. The sprite deletions, `tools/reminders-helper/`, `settings/`, and any `claude/` files belong to other work — never stage them.
3. **Before editing any shared/contested file** (`apps/desktop/src/main/App.tsx`, `apps/desktop/src/lib/api.ts`, `apps/desktop/src/lib/icons.tsx`), **re-Read it fresh immediately before each Edit.** It may have changed. Preserve unrelated content you find — especially the `claude` tab and `ClaudeTerminal` wiring in `App.tsx`. The Edit tool's exact-match will fail safe rather than corrupt; if it fails, re-Read and adapt.
4. **`icons.tsx` is untracked**: adding `MailIcon` and committing it will commit the whole file (including icons another feature added). That's fine — it's a shared icon library. Do not split it.
5. **If a verification step reveals a genuine merge/edit collision with concurrent work you cannot cleanly resolve, STOP and report** rather than forcing. Backend tasks (1–9) touch files no other agent is editing and are safe to run start-to-finish; the contested surface is only the three frontend files above (Tasks 10–13).
6. New backend files (`agents/daily_brief.py`, `agents/email_render.py`, `runtime/daily_job.py`, `store/repos/snapshot_repo.py`, `models/daily_brief.py`, and their tests) are exclusive to this feature — no contention.

---

## File Structure

**Backend (create):**
- `services/api/src/irma_api/store/repos/snapshot_repo.py` — `DailySnapshot` dataclass + `SnapshotRepo` (upsert / get / latest_before).
- `services/api/src/irma_api/models/daily_brief.py` — `ProjectProgress`, `LookaheadItem`, `DailyBrief` pydantic models.
- `services/api/src/irma_api/agents/daily_brief.py` — `compute_progress()` pure fn + `DailyBriefService`.
- `services/api/src/irma_api/agents/email_render.py` — `render_daily_email()` pure fn.
- `services/api/src/irma_api/runtime/daily_job.py` — `DailyBriefJob` (idempotent send wrapper).
- Tests: `tests/test_snapshot_repo.py`, `tests/test_progress_delta.py`, `tests/test_daily_brief_service.py`, `tests/test_email_render.py`, `tests/test_daily_job.py`, `tests/test_scheduler_daily.py`, `tests/test_routers_brief_email.py`.

**Backend (modify):**
- `services/api/src/irma_api/config.py` — 4 new settings.
- `services/api/src/irma_api/store/migrations.py` — `daily_snapshot` table.
- `services/api/src/irma_api/runtime/scheduler.py` — `add_daily_job()`.
- `services/api/src/irma_api/routers/brief.py` — `POST /email`.
- `services/api/src/irma_api/app.py` — wire service + job + cron.
- `services/api/.env.example` — document new settings.
- `services/api/tests/test_migrations.py` — assert new table.

**Frontend (modify):**
- `apps/desktop/src/lib/api.ts` — add `sendBriefEmail()`, remove `fetchBrief`.
- `apps/desktop/src/lib/icons.tsx` — add `MailIcon`.
- `apps/desktop/src/main/App.tsx` — remove Brief tab, swap Refresh→Brief button.

**Frontend (delete):**
- `apps/desktop/src/main/brief/BriefView.tsx`.

---

## Task 0: Pre-flight (no commits)

- [ ] **Step 1: Record the starting state**

Run: `cd /Users/amit/Documents/Code/Irma && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD && git status --porcelain | wc -l`
Note the branch (expected `feat/chat-tools-parity`), HEAD sha, and dirty count. If the branch is NOT `feat/chat-tools-parity`, STOP and report — the working-tree assumptions may not hold.

- [ ] **Step 2: Confirm the untracked dependencies are present**

Run: `ls apps/desktop/src/lib/icons.tsx apps/desktop/src/main/App.tsx && cd services/api && uv run python -c "import irma_api.tools.resend, irma_api.tools.calendar, irma_api.agents.lead_agent" && echo OK`
Expected: files listed + `OK`. If `icons.tsx` is missing, STOP — the frontend tasks cannot proceed.

- [ ] **Step 3: Quiescence check (avoid colliding with a live agent)**

Run: `cd /Users/amit/Documents/Code/Irma && find apps/desktop/src services/api/src -name '*.tsx' -o -name '*.ts' -o -name '*.py' -newermt '-90 seconds' 2>/dev/null | head`
If files were modified in the last 90s, another agent is likely mid-edit. Wait ~2 minutes and re-check before starting the **frontend** tasks (10–13). Backend tasks (1–9) are safe regardless. Do not abort the whole run for this — just sequence the frontend work after quiescence.

- [ ] **Step 4: Proceed.** No commit in this task.

---

## Task 1: Config + .env.example

**Files:**
- Modify: `services/api/src/irma_api/config.py`
- Modify: `services/api/.env.example`
- Test: `services/api/tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_settings.py`:

```python
def test_daily_brief_defaults() -> None:
    from irma_api.config import Settings

    s = Settings()
    assert s.irma_daily_brief_enabled is True
    assert s.irma_brief_timezone == "Asia/Jerusalem"
    assert s.irma_brief_hour == 8
    assert s.irma_brief_lookahead_days == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_settings.py::test_daily_brief_defaults -v`
Expected: FAIL (`AttributeError`/`ValidationError` — fields don't exist).

- [ ] **Step 3: Add the settings**

In `services/api/src/irma_api/config.py`, immediately after the `irma_api_port: int = 8765` line (end of the HTTP block), add:

```python

    # --- Daily email brief ---------------------------------------------------
    # The morning brief is emailed via the Resend tool. Disable to skip the
    # 8am cron entirely (the on-demand Brief button still works).
    irma_daily_brief_enabled: bool = True
    irma_brief_timezone: str = "Asia/Jerusalem"
    irma_brief_hour: int = 8
    irma_brief_lookahead_days: int = 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_settings.py::test_daily_brief_defaults -v`
Expected: PASS.

- [ ] **Step 5: Document in .env.example**

Append to `services/api/.env.example`:

```
# --- Daily email brief ---
# Emailed every morning at IRMA_BRIEF_HOUR in IRMA_BRIEF_TIMEZONE via Resend.
# Requires RESEND_API_KEY + IRMA_USER_EMAIL (the send_email recipient lock).
IRMA_DAILY_BRIEF_ENABLED=true
IRMA_BRIEF_TIMEZONE=Asia/Jerusalem
IRMA_BRIEF_HOUR=8
IRMA_BRIEF_LOOKAHEAD_DAYS=3
```

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/config.py services/api/.env.example services/api/tests/test_settings.py
git commit -m "feat(config): daily-brief schedule + lookahead settings"
```

---

## Task 2: daily_snapshot table + SnapshotRepo

**Files:**
- Modify: `services/api/src/irma_api/store/migrations.py`
- Create: `services/api/src/irma_api/store/repos/snapshot_repo.py`
- Test: `services/api/tests/test_snapshot_repo.py`, `services/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing repo test**

Create `services/api/tests/test_snapshot_repo.py`:

```python
"""SnapshotRepo: upsert idempotency + latest-before baseline lookup."""

from __future__ import annotations

from datetime import date

import aiosqlite
import pytest

from irma_api.store.repos.snapshot_repo import SnapshotRepo


@pytest.mark.asyncio
async def test_get_miss_returns_none(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    assert await repo.get(date(2026, 5, 30)) is None


@pytest.mark.asyncio
async def test_upsert_then_get(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    await repo.upsert(
        date(2026, 5, 30),
        per_project_counts={"p1": {"open": 2, "done": 1}},
        completed_task_ids=["t9"],
    )
    snap = await repo.get(date(2026, 5, 30))
    assert snap is not None
    assert snap.per_project_counts == {"p1": {"open": 2, "done": 1}}
    assert snap.completed_task_ids == ["t9"]


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_date(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    await repo.upsert(date(2026, 5, 30), per_project_counts={}, completed_task_ids=[])
    await repo.upsert(
        date(2026, 5, 30),
        per_project_counts={"p1": {"open": 0, "done": 3}},
        completed_task_ids=["a", "b", "c"],
    )
    snap = await repo.get(date(2026, 5, 30))
    assert snap is not None
    assert snap.completed_task_ids == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_latest_before_picks_most_recent_prior(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    await repo.upsert(date(2026, 5, 28), per_project_counts={}, completed_task_ids=["x"])
    await repo.upsert(date(2026, 5, 29), per_project_counts={}, completed_task_ids=["y"])
    await repo.upsert(date(2026, 5, 30), per_project_counts={}, completed_task_ids=["z"])
    baseline = await repo.latest_before(date(2026, 5, 30))
    assert baseline is not None
    assert baseline.snapshot_date == date(2026, 5, 29)
    assert baseline.completed_task_ids == ["y"]


@pytest.mark.asyncio
async def test_latest_before_none_when_empty(db_conn: aiosqlite.Connection) -> None:
    repo = SnapshotRepo(db_conn)
    assert await repo.latest_before(date(2026, 5, 30)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_snapshot_repo.py -v`
Expected: FAIL (`ModuleNotFoundError: snapshot_repo`).

- [ ] **Step 3: Add the migration**

In `services/api/src/irma_api/store/migrations.py`, add this statement to the `SCHEMA_STATEMENTS` tuple, immediately before the final `"DROP TABLE IF EXISTS briefs",` line:

```python
    """
    CREATE TABLE IF NOT EXISTS daily_snapshot (
        snapshot_date       TEXT PRIMARY KEY,
        per_project_counts  TEXT NOT NULL DEFAULT '{}',
        completed_task_ids  TEXT NOT NULL DEFAULT '[]',
        created_at          TEXT NOT NULL
    )
    """,
```

- [ ] **Step 4: Implement SnapshotRepo**

Create `services/api/src/irma_api/store/repos/snapshot_repo.py`:

```python
"""Async access for the `daily_snapshot` table.

One row per local calendar day, keyed by ISO date. Stores per-project open/done
task counts and the set of completed task ids as of that snapshot, so the daily
brief can compute day-over-day progress against the most recent prior row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import aiosqlite


@dataclass(frozen=True)
class DailySnapshot:
    snapshot_date: date
    per_project_counts: dict[str, dict[str, int]]
    completed_task_ids: list[str]
    created_at: datetime


def _row_to_snapshot(row: aiosqlite.Row) -> DailySnapshot:
    return DailySnapshot(
        snapshot_date=date.fromisoformat(row["snapshot_date"]),
        per_project_counts=json.loads(row["per_project_counts"]),
        completed_task_ids=json.loads(row["completed_task_ids"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SnapshotRepo:
    """Pure data access for `daily_snapshot` rows."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def upsert(
        self,
        snapshot_date: date,
        *,
        per_project_counts: dict[str, dict[str, int]],
        completed_task_ids: list[str],
    ) -> None:
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO daily_snapshot
                (snapshot_date, per_project_counts, completed_task_ids, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                snapshot_date.isoformat(),
                json.dumps(per_project_counts),
                json.dumps(completed_task_ids),
                datetime.now(UTC).replace(microsecond=0).isoformat(),
            ),
        )
        await self._conn.commit()

    async def get(self, snapshot_date: date) -> DailySnapshot | None:
        cur = await self._conn.execute(
            "SELECT * FROM daily_snapshot WHERE snapshot_date = ?",
            (snapshot_date.isoformat(),),
        )
        row = await cur.fetchone()
        return _row_to_snapshot(row) if row else None

    async def latest_before(self, snapshot_date: date) -> DailySnapshot | None:
        cur = await self._conn.execute(
            """
            SELECT * FROM daily_snapshot
            WHERE snapshot_date < ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (snapshot_date.isoformat(),),
        )
        row = await cur.fetchone()
        return _row_to_snapshot(row) if row else None
```

- [ ] **Step 5: Run repo test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_snapshot_repo.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Add migration assertion**

Append to `services/api/tests/test_migrations.py`:

```python
@pytest.mark.asyncio
async def test_daily_snapshot_table_exists(db_conn: aiosqlite.Connection) -> None:
    cur = await db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_snapshot'"
    )
    assert await cur.fetchone() is not None
```

If `pytest` and `aiosqlite` are not already imported at the top of that test file, add `import aiosqlite` and `import pytest` as needed (check the file head first).

- [ ] **Step 7: Run migration test**

Run: `cd services/api && uv run pytest tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add services/api/src/irma_api/store/migrations.py services/api/src/irma_api/store/repos/snapshot_repo.py services/api/tests/test_snapshot_repo.py services/api/tests/test_migrations.py
git commit -m "feat(store): daily_snapshot table + SnapshotRepo"
```

---

## Task 3: Daily-brief models + progress delta

**Files:**
- Create: `services/api/src/irma_api/models/daily_brief.py`
- Create: `services/api/src/irma_api/agents/daily_brief.py` (this task adds only `compute_progress`)
- Test: `services/api/tests/test_progress_delta.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_progress_delta.py`:

```python
"""compute_progress: per-project day-over-day delta vs a baseline snapshot."""

from __future__ import annotations

from datetime import UTC, date, datetime

from irma_api.agents.daily_brief import compute_progress
from irma_api.models.project import Project, ProjectStatus
from irma_api.models.task import Task, TaskStatus
from irma_api.store.repos.snapshot_repo import DailySnapshot


def _project(pid: str, name: str) -> Project:
    now = datetime(2026, 5, 30, tzinfo=UTC)
    return Project(
        id=pid,
        name=name,
        description="",
        status=ProjectStatus.ACTIVE,
        priority=2,
        calendar_keywords=[],
        goals=[],
        target_date=None,
        created_at=now,
        updated_at=now,
    )


def _task(tid: str, pid: str, status: TaskStatus) -> Task:
    now = datetime(2026, 5, 30, tzinfo=UTC)
    return Task(
        id=tid,
        project_id=pid,
        title=f"task {tid}",
        notes="",
        status=status,
        due_date=None,
        scheduled_for=None,
        estimated_minutes=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def test_no_baseline_reports_absolute_counts() -> None:
    projects = [_project("p1", "Alpha")]
    tasks = [_task("t1", "p1", TaskStatus.TODO), _task("t2", "p1", TaskStatus.DONE)]
    out = compute_progress(projects, tasks, baseline=None)
    assert len(out) == 1
    assert out[0].project_name == "Alpha"
    assert out[0].open_now == 1
    assert out[0].done_now == 1
    assert out[0].completed_since == 0
    assert out[0].added_since == 0


def test_completed_since_counts_newly_done_ids() -> None:
    baseline = DailySnapshot(
        snapshot_date=date(2026, 5, 29),
        per_project_counts={"p1": {"open": 2, "done": 0}},
        completed_task_ids=[],
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    projects = [_project("p1", "Alpha")]
    tasks = [_task("t1", "p1", TaskStatus.DONE), _task("t2", "p1", TaskStatus.TODO)]
    out = compute_progress(projects, tasks, baseline=baseline)
    assert out[0].completed_since == 1  # t1 newly done
    assert out[0].open_now == 1
    assert out[0].done_now == 1


def test_added_since_is_total_count_growth_floored_at_zero() -> None:
    baseline = DailySnapshot(
        snapshot_date=date(2026, 5, 29),
        per_project_counts={"p1": {"open": 1, "done": 0}},
        completed_task_ids=[],
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    projects = [_project("p1", "Alpha")]
    tasks = [
        _task("t1", "p1", TaskStatus.TODO),
        _task("t2", "p1", TaskStatus.TODO),
        _task("t3", "p1", TaskStatus.DONE),
    ]
    out = compute_progress(projects, tasks, baseline=baseline)
    assert out[0].added_since == 2  # 3 total now vs 1 before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_progress_delta.py -v`
Expected: FAIL (`ModuleNotFoundError: models.daily_brief` / `agents.daily_brief`).

- [ ] **Step 3: Create the models**

Create `services/api/src/irma_api/models/daily_brief.py`:

```python
"""Models for the emailed daily brief.

The factual sections (`progress`, `today_focus`, `lookahead_tasks`,
`calendar_text`) are computed deterministically in Python. Only `narrative`,
`recommendation`, and `conflicts` come from the LLM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from irma_api.models.brief import FocusItem


class ProjectProgress(BaseModel):
    project_id: str
    project_name: str
    completed_since: int = 0
    added_since: int = 0
    open_now: int = 0
    done_now: int = 0
    note: str = ""


class LookaheadItem(BaseModel):
    title: str
    when: str  # ISO date
    kind: Literal["due", "scheduled"]
    project_name: str | None = None


class DailyBrief(BaseModel):
    generated_at: datetime
    narrative: str = ""
    recommendation: str = ""
    conflicts: list[str] = Field(default_factory=list)
    progress: list[ProjectProgress] = Field(default_factory=list)
    today_focus: list[FocusItem] = Field(default_factory=list)
    lookahead_tasks: list[LookaheadItem] = Field(default_factory=list)
    calendar_text: str | None = None
    has_baseline: bool = False
```

- [ ] **Step 4: Create agents/daily_brief.py with compute_progress only**

Create `services/api/src/irma_api/agents/daily_brief.py`:

```python
"""DailyBriefService — assembles the emailed morning brief.

This module also exposes `compute_progress`, the pure per-project day-over-day
delta used by the brief and unit-tested independently.
"""

from __future__ import annotations

from irma_api.models.daily_brief import ProjectProgress
from irma_api.models.project import Project
from irma_api.models.task import Task, TaskStatus
from irma_api.store.repos.snapshot_repo import DailySnapshot


def compute_progress(
    projects: list[Project],
    tasks: list[Task],
    *,
    baseline: DailySnapshot | None,
) -> list[ProjectProgress]:
    """Per-project delta of `tasks` (all statuses) vs `baseline`.

    completed_since = newly-done task ids for the project not present in the
    baseline's completed set. added_since = growth in total task count for the
    project vs the baseline counts, floored at 0.
    """
    baseline_completed = set(baseline.completed_task_ids) if baseline else set()
    out: list[ProjectProgress] = []
    for p in projects:
        p_tasks = [t for t in tasks if t.project_id == p.id]
        done_ids_now = {t.id for t in p_tasks if t.status == TaskStatus.DONE}
        open_now = sum(1 for t in p_tasks if t.status != TaskStatus.DONE)
        done_now = len(done_ids_now)
        completed_since = len(done_ids_now - baseline_completed)
        if baseline is not None:
            base = baseline.per_project_counts.get(p.id, {"open": 0, "done": 0})
            base_total = int(base.get("open", 0)) + int(base.get("done", 0))
        else:
            base_total = open_now + done_now
        added_since = max(0, (open_now + done_now) - base_total)
        out.append(
            ProjectProgress(
                project_id=p.id,
                project_name=p.name,
                completed_since=completed_since,
                added_since=added_since,
                open_now=open_now,
                done_now=done_now,
            )
        )
    return out
```

> Note: confirm the `Project` field is `.name` and `TaskStatus.DONE` exists by checking `models/project.py` and `models/task.py` before running — they do in this codebase.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_progress_delta.py -v`
Expected: PASS (3 tests). If `Project`/`Task` constructor kwargs differ, adjust the test helpers to match the real model fields (inspect `models/project.py` / `models/task.py`).

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/models/daily_brief.py services/api/src/irma_api/agents/daily_brief.py services/api/tests/test_progress_delta.py
git commit -m "feat(brief): daily-brief models + compute_progress delta"
```

---

## Task 4: DailyBriefService.build()

**Files:**
- Modify: `services/api/src/irma_api/agents/daily_brief.py`
- Test: `services/api/tests/test_daily_brief_service.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_daily_brief_service.py`:

```python
"""DailyBriefService.build(): context assembly, snapshot write, prose parse."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from irma_api.agents.daily_brief import DailyBriefService
from irma_api.agents.llm import TextResult
from irma_api.config import Settings
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate, TaskStatus
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
    settings = Settings(irma_db_path=Path("x"), irma_brief_lookahead_days=3)
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
    # lookahead picked up the due-tomorrow task
    assert any(it.title == "due-soon" for it in brief.lookahead_tasks)
    # snapshot for today was written
    snap = await SnapshotRepo(store.connection).get(today)
    assert snap is not None
    assert proj.id in snap.per_project_counts
    # progress present, no baseline yet
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
            return TextResult(
                text='{"narrative":"ok","recommendation":"go","conflicts":[]}'
            )

    llm = _FlakyLLM()
    settings = Settings(irma_db_path=Path("x"))
    svc = DailyBriefService(
        settings=settings, llm=llm, store=store, observers=[], bus=StateBus(), calendar=None
    )
    brief = await svc.build()
    assert llm.calls == 2
    assert brief.narrative == "ok"
```

> Before running: verify `ProjectCreate` / `TaskCreate` field names against `models/project.py` / `models/task.py` and adjust kwargs if needed (e.g. `target_date`, `status`). The `due_date` on `TaskCreate` is a `date`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_daily_brief_service.py -v`
Expected: FAIL (`ImportError: cannot import name 'DailyBriefService'`).

- [ ] **Step 3: Implement DailyBriefService**

Append to `services/api/src/irma_api/agents/daily_brief.py` (add the new imports to the existing import block at the top of the file, then add the class):

New imports to add at the top:

```python
import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.llm import ChatTurn, LLMClient, TextResult
from irma_api.agents.prompts import load_prompt
from irma_api.config import Settings
from irma_api.models.brief import FocusItem, FocusKind
from irma_api.models.daily_brief import DailyBrief, LookaheadItem
from irma_api.models.project import ProjectStatus
from irma_api.runtime.state import StateBus
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.snapshot_repo import SnapshotRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import ToolError
```

> The `Observer` type and `run_refresh` are imported lazily inside `build()` to avoid a circular import (`routers.signals` imports agents). Use a local import there.

Class body (append after `compute_progress`):

```python
logger = structlog.get_logger(__name__)

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")
_OPEN_STATUSES: Final = [TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED]


def _extract_json(text: str) -> str:
    stripped = _FENCE_RE.sub("", text.strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _parse_prose(text: str) -> tuple[str, str, list[str]]:
    data = json.loads(_extract_json(text))
    return (
        str(data["narrative"]),
        str(data["recommendation"]),
        [str(c) for c in data.get("conflicts", [])],
    )


class DailyBriefService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        store: SignalStore,
        observers: list,  # list[Observer]; loosely typed to dodge a circular import
        bus: StateBus,
        calendar: object | None,  # ReadCalendarTool | None
        max_tokens: int = 1200,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._store = store
        self._observers = observers
        self._bus = bus
        self._calendar = calendar
        self._max_tokens = max_tokens

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self._settings.irma_brief_timezone)).date()

    async def build(self) -> DailyBrief:
        from irma_api.routers.signals import run_refresh  # local: avoid circular import

        try:
            await run_refresh(store=self._store, observers=self._observers, bus=self._bus)
        except Exception as exc:  # noqa: BLE001 — observers must never block the brief
            logger.warning("daily_brief.refresh_failed", error=str(exc))

        today = self._today()
        window_end = today + timedelta(days=self._settings.irma_brief_lookahead_days)

        prepo = ProjectRepo(self._store.connection)
        trepo = TaskRepo(self._store.connection)
        projects = await prepo.list(statuses=[ProjectStatus.ACTIVE])
        all_tasks = await trepo.list()
        project_names = {p.id: p.name for p in projects}

        today_focus = [
            FocusItem(
                kind=FocusKind.TASK,
                title=t.title,
                project_id=t.project_id,
                project_name=project_names.get(t.project_id),
                task_id=t.id,
                due_date=t.due_date.isoformat() if t.due_date else None,
                scheduled_for=t.scheduled_for.isoformat() if t.scheduled_for else None,
            )
            for t in all_tasks
            if t.status in _OPEN_STATUSES
            and (t.due_date == today or t.scheduled_for == today)
        ]

        lookahead: list[LookaheadItem] = []
        for t in all_tasks:
            if t.status not in _OPEN_STATUSES:
                continue
            if t.due_date is not None and today < t.due_date <= window_end:
                lookahead.append(
                    LookaheadItem(
                        title=t.title,
                        when=t.due_date.isoformat(),
                        kind="due",
                        project_name=project_names.get(t.project_id),
                    )
                )
            elif t.scheduled_for is not None and today < t.scheduled_for <= window_end:
                lookahead.append(
                    LookaheadItem(
                        title=t.title,
                        when=t.scheduled_for.isoformat(),
                        kind="scheduled",
                        project_name=project_names.get(t.project_id),
                    )
                )
        lookahead.sort(key=lambda it: it.when)

        calendar_text = await self._read_calendar()

        baseline = await SnapshotRepo(self._store.connection).latest_before(today)
        progress = compute_progress(projects, all_tasks, baseline=baseline)

        narrative, recommendation, conflicts = await self._synthesize(
            today=today,
            progress=progress,
            today_focus=today_focus,
            lookahead=lookahead,
            calendar_text=calendar_text,
        )

        await SnapshotRepo(self._store.connection).upsert(
            today,
            per_project_counts={
                p.project_id: {"open": p.open_now, "done": p.done_now} for p in progress
            },
            completed_task_ids=[
                t.id for t in all_tasks if t.status == TaskStatus.DONE
            ],
        )

        return DailyBrief(
            generated_at=datetime.now(UTC),
            narrative=narrative,
            recommendation=recommendation,
            conflicts=conflicts,
            progress=progress,
            today_focus=today_focus,
            lookahead_tasks=lookahead,
            calendar_text=calendar_text,
            has_baseline=baseline is not None,
        )

    async def _read_calendar(self) -> str | None:
        if self._calendar is None:
            return None
        try:
            text = await self._calendar.call(
                {"days": self._settings.irma_brief_lookahead_days}
            )
            return str(text)
        except ToolError as exc:
            logger.info("daily_brief.calendar_skipped", code=exc.code)
            return None

    async def _synthesize(
        self,
        *,
        today: date,
        progress: list,
        today_focus: list,
        lookahead: list[LookaheadItem],
        calendar_text: str | None,
    ) -> tuple[str, str, list[str]]:
        system = load_prompt("irma_persona")
        user = self._compose(today, progress, today_focus, lookahead, calendar_text)
        messages = [ChatTurn(role="user", content=user)]
        outcome = await self._llm.complete(
            system=system, messages=messages, max_tokens=self._max_tokens
        )
        text = outcome.text if isinstance(outcome, TextResult) else ""
        try:
            return _parse_prose(text)
        except (KeyError, ValueError):
            messages.append(ChatTurn(role="assistant", content=text))
            messages.append(
                ChatTurn(
                    role="user",
                    content=(
                        "That did not parse. Reply with ONLY a JSON object: "
                        '{"narrative": str, "recommendation": str, "conflicts": [str]}'
                    ),
                )
            )
            retry = await self._llm.complete(
                system=system, messages=messages, max_tokens=self._max_tokens
            )
            retry_text = retry.text if isinstance(retry, TextResult) else ""
            return _parse_prose(retry_text)

    def _compose(
        self,
        today: date,
        progress: list,
        today_focus: list,
        lookahead: list[LookaheadItem],
        calendar_text: str | None,
    ) -> str:
        lines: list[str] = [
            f"TODAY: {today.isoformat()}",
            "You are writing the operator's morning brief email.",
            "",
            "PROGRESS SINCE LAST BRIEF (per project):",
        ]
        for p in progress:
            lines.append(
                f"  • {p.project_name}: {p.completed_since} completed, "
                f"{p.added_since} added — {p.open_now} open / {p.done_now} done"
            )
        lines.append("")
        lines.append("TODAY'S FOCUS:")
        lines.extend(f"  • {f.title}" for f in today_focus) or lines.append("  (none)")
        lines.append("")
        lines.append(f"NEXT {self._settings.irma_brief_lookahead_days} DAYS (task deadlines):")
        if lookahead:
            lines.extend(
                f"  • {it.when} {it.title} ({it.kind})" for it in lookahead
            )
        else:
            lines.append("  (none)")
        lines.append("")
        lines.append("CALENDAR (next few days):")
        lines.append(calendar_text or "  (calendar unavailable)")
        lines.append("")
        lines.append(
            "Reply with ONLY a JSON object (no markdown fence): "
            '{"narrative": <2-3 warm sentences in Irma\'s voice summarising the day>, '
            '"recommendation": <one concrete suggestion>, '
            '"conflicts": [<zero or more short strings on clashes/overload>]}'
        )
        return "\n".join(lines)
```

> The `lines.extend(...) or lines.append(...)` idiom on the focus line works because `list.extend` returns `None`; when `today_focus` is empty the `extend` is a no-op and the `append("  (none)")` runs. If this reads as too clever during review, replace with an explicit `if today_focus: ... else: ...`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_daily_brief_service.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Type-check this module**

Run: `cd services/api && uv run mypy --strict src/irma_api/agents/daily_brief.py`
Expected: no errors. If `observers: list` / `calendar: object | None` trip strict-mode rules, keep them as-is (intentional loose typing to avoid the circular import) — `mypy --strict` tolerates bare `list` only with `list[...]`; if it complains, annotate as `list[object]` and cast where used, or import `Observer`/`ReadCalendarTool` under `if TYPE_CHECKING:` and use string annotations. Prefer the `TYPE_CHECKING` route:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from irma_api.agents.base import Observer
    from irma_api.tools.calendar import ReadCalendarTool
```

then annotate `observers: list["Observer"]` and `calendar: "ReadCalendarTool | None"`.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/agents/daily_brief.py services/api/tests/test_daily_brief_service.py
git commit -m "feat(brief): DailyBriefService.build() with progress + lookahead + prose"
```

---

## Task 5: Email renderer

**Files:**
- Create: `services/api/src/irma_api/agents/email_render.py`
- Test: `services/api/tests/test_email_render.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_email_render.py`:

```python
"""render_daily_email: deterministic plain-text formatting."""

from __future__ import annotations

from datetime import UTC, date, datetime

from irma_api.agents.email_render import render_daily_email
from irma_api.models.brief import FocusItem, FocusKind
from irma_api.models.daily_brief import DailyBrief, LookaheadItem, ProjectProgress


def _brief(**kw) -> DailyBrief:
    base = dict(
        generated_at=datetime(2026, 5, 30, 5, 0, tzinfo=UTC),
        narrative="Good morning.",
        recommendation="Freeze code tonight.",
        conflicts=[],
        progress=[],
        today_focus=[],
        lookahead_tasks=[],
        calendar_text=None,
        has_baseline=True,
    )
    base.update(kw)
    return DailyBrief(**base)


def test_subject_uses_local_date() -> None:
    subject, _ = render_daily_email(_brief(), date(2026, 5, 30))
    assert subject == "Irma · Daily Brief — Sat 30 May"


def test_body_includes_sections_when_present() -> None:
    brief = _brief(
        progress=[
            ProjectProgress(
                project_id="p1", project_name="Alpha",
                completed_since=2, added_since=1, open_now=3, done_now=5,
            )
        ],
        today_focus=[FocusItem(kind=FocusKind.TASK, title="write spec")],
        lookahead_tasks=[
            LookaheadItem(title="submit", when="2026-06-01", kind="due", project_name="Alpha")
        ],
        conflicts=["MIT block clashes with deploy"],
    )
    _, body = render_daily_email(brief, date(2026, 5, 30))
    assert "Good morning." in body
    assert "PROGRESS SINCE YOUR LAST BRIEF" in body
    assert "Alpha" in body and "2 done" in body
    assert "TODAY'S FOCUS" in body and "write spec" in body
    assert "NEXT 3 DAYS" in body and "submit" in body
    assert "HEADS-UP" in body and "MIT block" in body
    assert "Freeze code tonight." in body


def test_first_brief_label_when_no_baseline() -> None:
    brief = _brief(
        has_baseline=False,
        progress=[
            ProjectProgress(
                project_id="p1", project_name="Alpha",
                completed_since=0, added_since=0, open_now=2, done_now=0,
            )
        ],
    )
    _, body = render_daily_email(brief, date(2026, 5, 30))
    assert "first brief" in body.lower()


def test_empty_sections_are_omitted() -> None:
    _, body = render_daily_email(_brief(), date(2026, 5, 30))
    assert "TODAY'S FOCUS" not in body
    assert "NEXT 3 DAYS" not in body
    assert "HEADS-UP" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_email_render.py -v`
Expected: FAIL (`ModuleNotFoundError: email_render`).

- [ ] **Step 3: Implement the renderer**

Create `services/api/src/irma_api/agents/email_render.py`:

```python
"""render_daily_email — turn a DailyBrief into a plain-text email (subject, body).

Pure function. Empty sections are omitted. The factual numbers come straight
from the computed DailyBrief fields; only the narrative/recommendation prose is
LLM-authored.
"""

from __future__ import annotations

from datetime import date

from irma_api.models.daily_brief import DailyBrief


def render_daily_email(brief: DailyBrief, today: date) -> tuple[str, str]:
    subject = f"Irma · Daily Brief — {today.strftime('%a %d %b')}"
    lines: list[str] = []

    if brief.narrative:
        lines += [brief.narrative, ""]

    if brief.progress:
        if brief.has_baseline:
            lines.append("PROGRESS SINCE YOUR LAST BRIEF")
            for p in brief.progress:
                lines.append(
                    f"  • {p.project_name}: {p.completed_since} done, "
                    f"{p.added_since} added — {p.open_now} open / {p.done_now} done"
                )
        else:
            lines.append("PROJECT STATUS (first brief — no prior baseline yet)")
            for p in brief.progress:
                lines.append(
                    f"  • {p.project_name}: {p.open_now} open / {p.done_now} done"
                )
        lines.append("")

    if brief.today_focus:
        lines.append("TODAY'S FOCUS")
        for f in brief.today_focus:
            suffix = f" (due {f.due_date})" if f.due_date else ""
            lines.append(f"  • {f.title}{suffix}")
        lines.append("")

    if brief.lookahead_tasks or brief.calendar_text:
        lines.append("NEXT 3 DAYS")
        for it in brief.lookahead_tasks:
            proj = f" [{it.project_name}]" if it.project_name else ""
            lines.append(f"  • {it.when} — {it.title}{proj} ({it.kind})")
        if brief.calendar_text:
            lines.append("")
            lines.append(brief.calendar_text)
        lines.append("")

    if brief.conflicts:
        lines.append("HEADS-UP")
        for c in brief.conflicts:
            lines.append(f"  • {c}")
        lines.append("")

    if brief.recommendation:
        lines.append(brief.recommendation)

    body = "\n".join(lines).rstrip() + "\n"
    return subject, body
```

> Note: the "NEXT 3 DAYS" heading is a fixed label; if `irma_brief_lookahead_days` is ever changed from 3, update this string (acceptable hard-coding for now — the setting default is 3 and the test asserts "NEXT 3 DAYS"). If you prefer it dynamic, pass `lookahead_days` into the renderer and format it; keep the test in sync.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_email_render.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/agents/email_render.py services/api/tests/test_email_render.py
git commit -m "feat(brief): plain-text daily email renderer"
```

---

## Task 6: DailyBriefJob (idempotent send wrapper)

**Files:**
- Create: `services/api/src/irma_api/runtime/daily_job.py`
- Test: `services/api/tests/test_daily_job.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_daily_job.py`:

```python
"""DailyBriefJob: date-keyed idempotency + force override."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from irma_api.config import Settings
from irma_api.models.daily_brief import DailyBrief
from irma_api.runtime.daily_job import DailyBriefJob


class _FakeService:
    def __init__(self) -> None:
        self.builds = 0

    async def build(self) -> DailyBrief:
        self.builds += 1
        return DailyBrief(generated_at=datetime.now(UTC), narrative="hi")


class _FakeSender:
    def __init__(self) -> None:
        self.sends: list[dict] = []

    async def call(self, args: dict) -> str:
        self.sends.append(args)
        return "sent (message id fake-123)"


def _settings() -> Settings:
    return Settings(irma_brief_timezone="Asia/Jerusalem")


@pytest.mark.asyncio
async def test_first_run_sends_and_records_date() -> None:
    svc, sender = _FakeService(), _FakeSender()
    job = DailyBriefJob(service=svc, sender=sender, settings=_settings())
    result = await job.run_once()
    assert result["sent"] is True
    assert len(sender.sends) == 1
    assert "subject" in sender.sends[0] and "body" in sender.sends[0]
    today = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    assert job.last_sent_date == today


@pytest.mark.asyncio
async def test_second_run_same_day_is_skipped() -> None:
    svc, sender = _FakeService(), _FakeSender()
    job = DailyBriefJob(service=svc, sender=sender, settings=_settings())
    job.last_sent_date = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    result = await job.run_once()
    assert result["sent"] is False
    assert sender.sends == []
    assert svc.builds == 0


@pytest.mark.asyncio
async def test_force_bypasses_idempotency() -> None:
    svc, sender = _FakeService(), _FakeSender()
    job = DailyBriefJob(service=svc, sender=sender, settings=_settings())
    job.last_sent_date = datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    result = await job.run_once(force=True)
    assert result["sent"] is True
    assert len(sender.sends) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_daily_job.py -v`
Expected: FAIL (`ModuleNotFoundError: daily_job`).

- [ ] **Step 3: Implement DailyBriefJob**

Create `services/api/src/irma_api/runtime/daily_job.py`:

```python
"""DailyBriefJob — builds, renders, and sends the daily brief once per day.

The cron callback calls run_once() (idempotent: at most one send per local
calendar day). The on-demand endpoint calls run_once(force=True). Idempotency
state is in-memory: a strict 8am policy means a missed morning is simply not
sent — there is no startup catch-up.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

import structlog

from irma_api.agents.email_render import render_daily_email
from irma_api.config import Settings
from irma_api.models.daily_brief import DailyBrief

logger = structlog.get_logger(__name__)


class _Builder(Protocol):
    async def build(self) -> DailyBrief: ...


class _Sender(Protocol):
    async def call(self, args: dict[str, str]) -> str: ...


class DailyBriefJob:
    def __init__(self, *, service: _Builder, sender: _Sender, settings: Settings) -> None:
        self._service = service
        self._sender = sender
        self._tz = ZoneInfo(settings.irma_brief_timezone)
        self.last_sent_date: date | None = None

    def _today(self) -> date:
        return datetime.now(self._tz).date()

    async def run_once(self, *, force: bool = False) -> dict[str, object]:
        today = self._today()
        if not force and self.last_sent_date == today:
            logger.info("daily_brief.skipped", reason="already_sent", date=today.isoformat())
            return {"sent": False, "reason": "already_sent"}

        brief = await self._service.build()
        subject, body = render_daily_email(brief, today)
        result = await self._sender.call({"subject": subject, "body": body})
        self.last_sent_date = today
        logger.info("daily_brief.sent", date=today.isoformat(), result=result)
        return {"sent": True, "result": result}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_daily_job.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/runtime/daily_job.py services/api/tests/test_daily_job.py
git commit -m "feat(runtime): DailyBriefJob idempotent send wrapper"
```

---

## Task 7: Scheduler.add_daily_job

**Files:**
- Modify: `services/api/src/irma_api/runtime/scheduler.py`
- Test: `services/api/tests/test_scheduler_daily.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_scheduler_daily.py`:

```python
"""Scheduler.add_daily_job registers a CronTrigger at the configured hour/tz."""

from __future__ import annotations

import pytest
from apscheduler.triggers.cron import CronTrigger

from irma_api.runtime.scheduler import Scheduler


@pytest.mark.asyncio
async def test_add_daily_job_registers_cron() -> None:
    async def _noop() -> None:
        return None

    sched = Scheduler(refresh_minutes=30, on_tick=_noop)
    sched.add_daily_job(_noop, hour=8, timezone="Asia/Jerusalem")

    job = sched._sched.get_job("irma-daily-brief")
    assert job is not None
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    assert str(trigger.timezone) == "Asia/Jerusalem"
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "8"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_scheduler_daily.py -v`
Expected: FAIL (`AttributeError: 'Scheduler' object has no attribute 'add_daily_job'`).

- [ ] **Step 3: Implement add_daily_job**

In `services/api/src/irma_api/runtime/scheduler.py`, add the import near the top (next to the `IntervalTrigger` import):

```python
from apscheduler.triggers.cron import CronTrigger
```

Then add this method to the `Scheduler` class (after `start`, before `shutdown`):

```python
    def add_daily_job(
        self,
        callback: Callable[[], Awaitable[object]],
        *,
        hour: int,
        timezone: str,
    ) -> None:
        """Register the once-a-day brief send at `hour`:00 in `timezone`.

        Safe to call before or after start(); APScheduler schedules it either
        way. Strict policy: the job only fires if the process is running at the
        trigger time — there is no catch-up for a missed morning.
        """
        self._sched.add_job(
            callback,
            trigger=CronTrigger(hour=hour, minute=0, timezone=timezone),
            id="irma-daily-brief",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("scheduler.daily_job_added", hour=hour, timezone=timezone)
```

> `Callable` and `Awaitable` are already imported at the top of the file. The callback returns `object` (DailyBriefJob.run_once returns a dict) — APScheduler ignores the return value.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_scheduler_daily.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/runtime/scheduler.py services/api/tests/test_scheduler_daily.py
git commit -m "feat(runtime): Scheduler.add_daily_job cron registration"
```

---

## Task 8: POST /api/v1/brief/email

**Files:**
- Modify: `services/api/src/irma_api/routers/brief.py`
- Test: `services/api/tests/test_routers_brief_email.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_routers_brief_email.py`:

```python
"""POST /api/v1/brief/email: 503 unconfigured, 200 + status when wired."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.brief import router as brief_router


@pytest_asyncio.fixture
async def make_client():
    async def _make(job: object | None) -> AsyncClient:
        app = FastAPI()
        app.state.daily_brief_job = job
        app.include_router(brief_router, prefix="/api/v1")
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://t")

    return _make


@pytest.mark.asyncio
async def test_email_503_without_job(make_client) -> None:
    client = await make_client(None)
    async with client:
        r = await client.post("/api/v1/brief/email")
    assert r.status_code == 503
    assert r.json()["error"] == "email_unavailable"


@pytest.mark.asyncio
async def test_email_200_sends(make_client) -> None:
    class _FakeJob:
        def __init__(self) -> None:
            self.forced = False

        async def run_once(self, *, force: bool = False) -> dict[str, object]:
            self.forced = force
            return {"sent": True, "result": "sent (message id fake-9)"}

    job = _FakeJob()
    client = await make_client(job)
    async with client:
        r = await client.post("/api/v1/brief/email")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"
    assert "fake-9" in body["detail"]
    assert job.forced is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_routers_brief_email.py -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Implement the endpoint**

In `services/api/src/irma_api/routers/brief.py`, add the endpoint at the end of the file. Keep the existing GET routes untouched. Append:

```python
@router.post("/email")
async def send_brief_email(request: Request) -> JSONResponse:
    """Build today's brief and email it now (on-demand 'Brief' button).

    Bypasses the once-a-day idempotency guard — always re-sends.
    """
    job = getattr(request.app.state, "daily_brief_job", None)
    if job is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "email_unavailable",
                "detail": "daily brief requires a configured LLM + Resend (RESEND_API_KEY, IRMA_USER_EMAIL)",
            },
            headers={"Retry-After": "30"},
        )
    try:
        result = await job.run_once(force=True)
    except Exception as exc:  # noqa: BLE001 — surface send failures as 502
        return JSONResponse(
            status_code=502,
            content={"error": "email_send_failed", "detail": str(exc)},
        )
    return JSONResponse(
        status_code=200,
        content={"status": "sent", "detail": str(result.get("result", ""))},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/api && uv run pytest tests/test_routers_brief_email.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/routers/brief.py services/api/tests/test_routers_brief_email.py
git commit -m "feat(api): POST /brief/email on-demand send"
```

---

## Task 9: Wire service + job + cron into app.py

**Files:**
- Modify: `services/api/src/irma_api/app.py`
- Test: `services/api/tests/test_app_boot.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_app_boot.py` (inspect the file head for its existing fixtures/imports first; it already boots the app via lifespan). Add:

```python
@pytest.mark.asyncio
async def test_app_exposes_daily_brief_job_attr() -> None:
    from irma_api.app import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        # attribute is always set (None when LLM/Resend unconfigured in test env)
        assert hasattr(app.state, "daily_brief_job")
```

> If `test_app_boot.py` already has a lifespan-context helper/fixture, reuse it instead of re-opening the context. The assertion only checks the attribute exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/api && uv run pytest tests/test_app_boot.py::test_app_exposes_daily_brief_job_attr -v`
Expected: FAIL (`AttributeError` — attr not set).

- [ ] **Step 3: Capture the tool instances**

In `services/api/src/irma_api/app.py`, the Resend and Calendar tools are currently appended to the `tools` list without keeping references. Capture them. Change the Resend block:

Find:
```python
    resend_key = secret_value_or_none(settings.resend_api_key)
    if resend_key is not None and settings.irma_user_email:
        tools.append(ResendSendTool(settings))
```
Replace with:
```python
    resend_key = secret_value_or_none(settings.resend_api_key)
    send_email_tool: ResendSendTool | None = None
    if resend_key is not None and settings.irma_user_email:
        send_email_tool = ResendSendTool(settings)
        tools.append(send_email_tool)
```

Find the calendar block:
```python
    if not calendar_missing:
        tools.append(ReadCalendarTool(settings))
        tools.append(CreateCalendarEventTool(settings))
```
Replace with:
```python
    read_calendar_tool: ReadCalendarTool | None = None
    if not calendar_missing:
        read_calendar_tool = ReadCalendarTool(settings)
        tools.append(read_calendar_tool)
        tools.append(CreateCalendarEventTool(settings))
```

- [ ] **Step 4: Build the service + job and register the cron**

In `services/api/src/irma_api/app.py`, after the `lead_agent` is constructed and `app.state.lead_agent = lead_agent` is set (and before the `async def tick()` definition), add:

```python
    daily_brief_job = None
    if llm is not None and send_email_tool is not None:
        from irma_api.agents.daily_brief import DailyBriefService
        from irma_api.runtime.daily_job import DailyBriefJob

        daily_service = DailyBriefService(
            settings=settings,
            llm=llm,
            store=store,
            observers=observers,
            bus=bus,
            calendar=read_calendar_tool,
        )
        daily_brief_job = DailyBriefJob(
            service=daily_service, sender=send_email_tool, settings=settings
        )
    else:
        logger.info(
            "app.daily_brief_disabled",
            has_llm=llm is not None,
            has_email=send_email_tool is not None,
        )
    app.state.daily_brief_job = daily_brief_job
```

Then, where the scheduler is started (after `scheduler.start()` / `app.state.scheduler = scheduler`), register the cron job:

```python
    if daily_brief_job is not None and settings.irma_daily_brief_enabled:
        async def daily_tick() -> None:
            await daily_brief_job.run_once()

        scheduler.add_daily_job(
            daily_tick,
            hour=settings.irma_brief_hour,
            timezone=settings.irma_brief_timezone,
        )
```

> Place the `add_daily_job` call after `scheduler.start()` — APScheduler accepts jobs added to a running scheduler. Keep the existing interval refresh job intact.

- [ ] **Step 5: Run the boot test + full suite**

Run: `cd services/api && uv run pytest tests/test_app_boot.py -v`
Expected: PASS.

Run: `cd services/api && uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Lint + type-check the backend**

Run: `cd services/api && uv run ruff check . && uv run mypy --strict src`
Expected: clean. Fix any issues (common: unused imports, missing annotations). Re-run until clean.

- [ ] **Step 7: Commit**

```bash
git add services/api/src/irma_api/app.py services/api/tests/test_app_boot.py
git commit -m "feat(app): wire DailyBriefService + cron + on-demand job"
```

---

## Task 10: Frontend API client

**Files:**
- Modify: `apps/desktop/src/lib/api.ts`

- [ ] **Step 1: Add sendBriefEmail and remove fetchBrief**

In `apps/desktop/src/lib/api.ts`, delete the entire `fetchBrief` function (the `// --- Brief ---` block, lines around 140-150) and replace it with:

```typescript
// --- Brief (email-only) ---------------------------------------------------

export async function sendBriefEmail(): Promise<{ status: string; detail: string }> {
  return jsonOrThrow(
    await fetch(url("/api/v1/brief/email"), { method: "POST" }),
  );
}
```

If `Horizon` was imported only for `fetchBrief`, remove it from the import block at the top of the file (check whether anything else uses `Horizon`). Leave the `Brief` type import only if still referenced elsewhere; otherwise remove it.

- [ ] **Step 2: Type-check**

Run: `cd apps/desktop && npx tsc --noEmit`
Expected: errors only in `App.tsx`/`BriefView.tsx` (fixed in Tasks 12-13), none in `api.ts`. If `api.ts` itself errors on an unused import, fix it here.

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src/lib/api.ts
git commit -m "feat(ui): sendBriefEmail API client; drop fetchBrief"
```

---

## Task 11: MailIcon

**Files:**
- Modify: `apps/desktop/src/lib/icons.tsx`

- [ ] **Step 1: Add the icon**

In `apps/desktop/src/lib/icons.tsx`, add after `RefreshIcon` (before `SettingsIcon`):

```tsx
export function MailIcon(props: IconProps) {
  return (
    <svg {...base(props)} aria-hidden="true">
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="m22 7-10 6L2 7" />
    </svg>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd apps/desktop && npx tsc --noEmit`
Expected: no new errors in `icons.tsx`.

- [ ] **Step 3: Commit**

> `icons.tsx` is currently **untracked**. `git add` will stage the whole file (including any icons another feature added) — that is acceptable for this shared icon library. If by execution time it is already tracked and contains others' edits, your `MailIcon` addition is still an isolated hunk in a shared file; commit it.

```bash
git add apps/desktop/src/lib/icons.tsx
git commit -m "feat(ui): MailIcon for the Brief button"
```

---

## Task 12: App.tsx — remove Brief tab, add Brief button

**Files:**
- Modify: `apps/desktop/src/main/App.tsx`

> ⚠️ **CONTESTED FILE.** Another agent added a `claude` tab + `ClaudeTerminal` to this file *after* this plan was written, and may add more. **Re-Read `App.tsx` in full immediately before each Edit below.** The snippets here reflect the version with the `claude` tab; if what you read differs, **adapt the edits to the actual content and preserve every tab/import you did not author (especially `claude`/`ClaudeTerminal`).** Your job is only: (a) remove the `brief` tab + `BriefView`, (b) swap the Refresh icon button for a Brief send button. Touch nothing else.

- [ ] **Step 0: Re-Read the current file**

Read `apps/desktop/src/main/App.tsx` fully now. Identify the actual import lines, the `Tab` union members, the brief-related state/effects, and the Header. Map the edits below onto what you actually see.

- [ ] **Step 1: Fix the imports**

Three changes to the import block, leaving all other imports (incl. `ClaudeTerminal`) intact:
- In the api import, replace `fetchBrief, forceRefresh` with `sendBriefEmail` (keep `listProjects`). Result: `import { sendBriefEmail, listProjects } from "../lib/api";`
- In the types import, drop `Brief` (keep `AgentState`, `Project`): `import type { AgentState, Project } from "../lib/types";`
- Remove the `import { BriefView } from "./brief/BriefView";` line entirely.
- In the icons import, replace `RefreshIcon` with `MailIcon` (keep `SettingsIcon`): `import { MailIcon, SettingsIcon } from "../lib/icons";`

- [ ] **Step 2: Update the Tab type and component body**

In the `type Tab = ...` union, **remove only the `"brief"` member, keeping all others** (`"projects" | "chat" | "claude" | "settings"` if `claude` is present; otherwise `"projects" | "chat" | "settings"`).

Inside `App()`, remove the brief state + synth effects. Delete these blocks:
```typescript
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
```
```typescript
  const synth = useCallback(async () => {
    setBriefBusy(true);
    setBriefError(null);
    try { setBrief(await fetchBrief("day")); }
    catch (e: unknown) { setBriefError(e instanceof Error ? e.message : String(e)); }
    finally { setBriefBusy(false); }
  }, []);

  // Pre-fetch the brief on mount so it's ready instantly when the user
  // clicks the Brief tab. Refire if the prior attempt errored and the user
  // later switches to the tab — gives them a retry path.
  useEffect(() => { void synth(); }, [synth]);
  useEffect(() => {
    if (tab === "brief" && !brief && !briefBusy && briefError) void synth();
  }, [tab, brief, briefBusy, briefError, synth]);
```
```typescript
  const refresh = useCallback(async () => {
    setRefreshBusy(true);
    try { await forceRefresh(); await loadProjects(); }
    catch (e) { console.error(e); }
    finally { setRefreshBusy(false); }
  }, [loadProjects]);
```

Add a brief-send handler in their place (after `loadProjects`/the SSE effect, before `closeWindow`):
```typescript
  const [briefSendState, setBriefSendState] =
    useState<"idle" | "sending" | "sent" | "error">("idle");

  const sendBrief = useCallback(async () => {
    setBriefSendState("sending");
    try {
      await sendBriefEmail();
      setBriefSendState("sent");
      setTimeout(() => setBriefSendState("idle"), 4000);
    } catch (e) {
      console.error("[dashboard] sendBriefEmail failed:", e);
      setBriefSendState("error");
      setTimeout(() => setBriefSendState("idle"), 4000);
    }
  }, []);
```

- [ ] **Step 3: Update the Header usage and the JSX**

Replace the `<Header ... />` element:
```tsx
      <Header
        tab={tab}
        onTabChange={setTab}
        agentState={agentState}
        onRefresh={refresh}
        refreshBusy={refreshBusy}
        onClose={closeWindow}
      />
```
with:
```tsx
      <Header
        tab={tab}
        onTabChange={setTab}
        agentState={agentState}
        onSendBrief={sendBrief}
        briefSendState={briefSendState}
        onClose={closeWindow}
      />
```

Remove the brief tab panel from `<main>`:
```tsx
        {tab === "brief" && (
          <BriefView brief={brief} busy={briefBusy} error={briefError} onRefetch={synth} />
        )}
```
(delete those lines entirely).

- [ ] **Step 4: Rewrite the Header component**

> Re-Read `App.tsx` first. The nav below includes a `claude` tab — **keep whatever tabs currently exist between Chat and the Brief button** (do not drop `claude`). The only structural change vs the current Header is: the props (`onRefresh`/`refreshBusy` → `onSendBrief`/`briefSendState`), and the Refresh icon button → the Brief send button. Adjust the snippet to match the real current tab set before pasting.

Replace the entire `Header` function with (this version assumes a `claude` tab exists — preserve it):

```tsx
function Header({
  tab, onTabChange, agentState, onSendBrief, briefSendState, onClose,
}: {
  tab: Tab;
  onTabChange: (t: Tab) => void;
  agentState: AgentState;
  onSendBrief: () => void;
  briefSendState: "idle" | "sending" | "sent" | "error";
  onClose: () => void;
}) {
  const stateColor = {
    idle: "var(--color-moss)",
    observing: "var(--color-amber)",
    thinking: "var(--color-red-hover)",
    alert: "var(--color-red)",
  }[agentState];

  const briefLabel = {
    idle: "Brief",
    sending: "Sending…",
    sent: "Sent ✓",
    error: "Failed",
  }[briefSendState];

  return (
    <header
      data-tauri-drag-region
      className="shrink-0 px-5 pt-3 pb-0 select-none border-b"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: stateColor }}
            aria-label={`agent ${agentState}`}
          />
          <h1 className="display text-[18px] font-semibold" style={{ color: "var(--color-ink)" }}>
            Irma
          </h1>
          <span className="text-[11px]" style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}>
            {agentState}
          </span>
        </div>
        <button onClick={onClose} aria-label="Close"
                className="px-2 py-1 text-[14px] leading-none rounded-md hover:bg-[var(--color-surface-2)]"
                style={{ color: "var(--color-ink-mute)" }}>
          ×
        </button>
      </div>
      <nav className="flex items-center gap-1 -mb-px">
        <Tab id="projects" current={tab} onClick={onTabChange}>Projects</Tab>
        <Tab id="chat"     current={tab} onClick={onTabChange}>Chat</Tab>
        <Tab id="claude"   current={tab} onClick={onTabChange}>Claude</Tab>
        <button
          type="button"
          onClick={() => onSendBrief()}
          disabled={briefSendState === "sending"}
          aria-label="Email today's brief"
          title="Email today's brief"
          className="ml-auto px-4 py-2 text-[13px] font-medium transition-colors flex items-center gap-1.5 disabled:opacity-50"
          style={{ color: "var(--color-ink-mute)", borderBottom: "2px solid transparent" }}
        >
          <MailIcon size={16} className={briefSendState === "sending" ? "animate-pulse" : undefined} />
          {briefLabel}
        </button>
        <Tab id="settings" current={tab} onClick={onTabChange}
             aria-label="Settings" title="Settings">
          <SettingsIcon size={16} />
        </Tab>
      </nav>
    </header>
  );
}
```

- [ ] **Step 5: Type-check + lint**

Run: `cd apps/desktop && npx tsc --noEmit`
Expected: no errors in `App.tsx` (BriefView import is gone). If `BriefView.tsx` still exists and references `fetchBrief`/`Brief`, it may error — fixed in Task 13.

Run (if the project has eslint configured): `cd apps/desktop && npm run lint`
Expected: clean (or no lint script — skip).

- [ ] **Step 6: Commit**

First check whether `App.tsx` carries *only* your edits: `git diff --stat apps/desktop/src/main/App.tsx`. If the claude-terminal work was committed before this run, your diff is clean — commit normally:

```bash
git add apps/desktop/src/main/App.tsx
git commit -m "feat(ui): email-only brief — drop Brief tab, add Brief send button"
```

If `App.tsx` still contains *uncommitted* concurrent work (e.g. the `claude` tab is not yet in any commit — verify with `git log --oneline -1 -- apps/desktop/src/main/App.tsx` and `git diff HEAD -- apps/desktop/src/main/App.tsx`), you cannot isolate hunks non-interactively. In that case, commit with a message that flags the bundling so history is honest:

```bash
git add apps/desktop/src/main/App.tsx
git commit -m "feat(ui): email-only brief — drop Brief tab, add Brief send button

Note: App.tsx also carried concurrent uncommitted claude-terminal tab changes
present in the working tree at commit time; they are included here."
```

---

## Task 13: Delete BriefView

**Files:**
- Delete: `apps/desktop/src/main/brief/BriefView.tsx`

- [ ] **Step 1: Confirm nothing else imports it**

Run: `cd apps/desktop && grep -rn "BriefView\|from \"./brief\|from \"../brief" src/`
Expected: no remaining references (App.tsx no longer imports it).

- [ ] **Step 2: Delete the file (and empty dir)**

```bash
git rm apps/desktop/src/main/brief/BriefView.tsx
# remove the now-empty brief/ dir if git leaves it (untracked dirs are auto-pruned)
rmdir apps/desktop/src/main/brief 2>/dev/null || true
```

- [ ] **Step 3: Type-check the whole frontend**

Run: `cd apps/desktop && npx tsc --noEmit`
Expected: clean (zero errors).

- [ ] **Step 4: Commit**

`git rm` already staged the deletion. Commit only that — do not `git add -A`:

```bash
git commit -m "chore(ui): remove dead BriefView (email-only brief)"
```

---

## Task 14: Full verification

- [ ] **Step 1: Backend — tests, lint, types**

Run: `cd services/api && uv run pytest -q && uv run ruff check . && uv run mypy --strict src`
Expected: all tests pass; ruff and mypy clean.

- [ ] **Step 2: Frontend — typecheck + build**

Run: `cd apps/desktop && npx tsc --noEmit && npm run build`
Expected: typecheck clean; Vite build succeeds.

- [ ] **Step 3: Manual smoke (optional, requires .env with RESEND + GOOGLE OAuth)**

If `services/api/.env` has `RESEND_API_KEY`, `IRMA_USER_EMAIL`, and Google OAuth set, verify the on-demand path end-to-end:

```bash
cd services/api && uv run uvicorn irma_api.app:create_app --factory --port 8765 &
sleep 3
curl -s -X POST http://127.0.0.1:8765/api/v1/brief/email | tee /dev/stderr
# expect {"status":"sent","detail":"sent (message id ...)"} and an email in the inbox
kill %1
```

If `.env` is not configured, expect `{"error":"email_unavailable",...}` with HTTP 503 — that is the correct unconfigured response.

- [ ] **Step 4: Final review commit (if any fixups were needed)**

Stage only daily-brief files that you changed during fixups — never `git add -A` (that would sweep in other agents' sprite deletions, `reminders-helper/`, `settings/`, `claude/`). List the specific paths, e.g.:

```bash
git add services/api/src/irma_api/agents/daily_brief.py services/api/tests/  # only files YOU touched
git commit -m "chore: daily email brief — verification fixups" || echo "nothing to fix up"
```

- [ ] **Step 5: Report**

Print a final summary: branch + HEAD sha, the list of commits you added (`git log --oneline <start-sha>..HEAD`), backend test/lint/type results, frontend typecheck/build results, and whether the on-demand smoke test ran or was skipped (unconfigured). Explicitly note that no branch was switched/created and no other agent's files were staged.

---

## Self-Review Notes (for the executor)

- **Spec coverage:** Task 1 (config/tz/hour/lookahead) · Task 2 (snapshot store) · Task 3 (models + progress delta) · Task 4 (service: refresh, focus, lookahead tasks∪calendar, progress, prose, snapshot write) · Task 5 (email render) · Task 6 (idempotent job, strict no-catch-up) · Task 7 (8am Asia/Jerusalem cron) · Task 8 (on-demand POST) · Task 9 (wiring) · Tasks 10-13 (email-only UI: drop tab, Brief button) — every spec section maps to a task.
- **Calendar lookahead deviation from spec:** the spec's `LookaheadItem` envisioned `kind: task|event`. `ReadCalendarTool.call()` returns a preformatted *string*, not structured events, so the implementation keeps task lookahead structured (`LookaheadItem`) and carries calendar as a raw `calendar_text` block. The email still shows both under "NEXT 3 DAYS." This is the robust choice given the tool's actual return type.
- **Model-field caveat:** the test helpers in Tasks 3-4 construct `Project`/`Task`/`ProjectCreate`/`TaskCreate` — verify exact field names against `models/project.py` and `models/task.py` before running and adjust kwargs if they differ. The implementation code only uses fields confirmed present (`.name`, `.id`, `.status`, `.due_date`, `.scheduled_for`, `.project_id`, `TaskStatus.{TODO,DOING,BLOCKED,DONE}`).
- **Circular import:** `routers.signals` imports from `agents`, so `DailyBriefService.build()` imports `run_refresh` locally; the `Observer`/`ReadCalendarTool` types use `TYPE_CHECKING` string annotations.
