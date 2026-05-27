# Project + Task Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the auto-observed `StandupBrief` with a manual `Project` + `Task` model and a horizon-aware `Brief` (`day`/`week`/`month`/`all`), shipped end-to-end with a minimal dashboard.

**Architecture:** SQLite gains `project`, `task`, `brief_cache` tables. `SignalStore` keeps the connection; three new pure-data repos (`ProjectRepo`, `TaskRepo`, `BriefCacheRepo`) read/write through it. `LeadAgent` is rewritten to dispatch on horizon, build a per-horizon context window, call `LLMClient.complete()`, and persist the parsed `Brief` to `brief_cache`. The dashboard gets two screens (`BriefView`, `ProjectsView`) behind a header tab switcher. `/standup` is deleted; `CodebaseAgent` is gated off behind `IRMA_CODEBASE_AGENT_ENABLED=false`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, `aiosqlite`, async `anthropic`/Ollama via the existing `LLMClient` abstraction, `pytest`/`pytest-asyncio`, `httpx.AsyncClient` for router tests, React 18 + TypeScript + Vite + Tailwind on the desktop side.

**Spec:** [`docs/superpowers/specs/2026-05-27-project-task-model-design.md`](../specs/2026-05-27-project-task-model-design.md)

---

## Deviations from spec (reconciled against current code)

The spec was written without re-reading every existing file. Three reconciliations land in this plan:

1. **`LLMClient` is the LLM seam** — the spec says "use the existing async `anthropic` client." Reality: `agents/llm.py` defines an `LLMClient` Protocol with two backends (`anthropic`, `ollama`) selectable via `IRMA_LLM_BACKEND`. The new `LeadAgent` uses `LLMClient.complete(system=, messages=, max_tokens=)` exactly like the current one, so swapping in a local model later is config-only.
2. **`StateBus` uses `publish()`, not `transition_to()`** — there is no context manager on the bus. The new `LeadAgent` calls `await bus.publish(THINKING)` at entry and `await bus.publish(IDLE or ALERT)` at exit, matching the existing pattern in `routers/standup.py` and `routers/signals.py`.
3. **`run_refresh` stops eagerly synthesizing** — today `run_refresh` calls `lead_agent.synthesize()` on every scheduled tick. The new design is lazy: `run_refresh` only observes + invalidates `brief_cache`. Briefs are computed on `GET /brief/<horizon>` cache miss.

## File map

```
services/api/src/irma_api/
├── models/
│   ├── project.py            CREATE  Project + ProjectStatus + Create/Update DTOs
│   ├── task.py               CREATE  Task + TaskStatus + Create/Update DTOs
│   └── brief.py              REWRITE Horizon, FocusItem, ProjectStatusItem, Brief (deletes StandupBrief)
├── store/
│   ├── errors.py             CREATE  NotFoundError, ConflictError
│   ├── migrations.py         MODIFY  add project/task/brief_cache tables + signals.project_id column
│   ├── sqlite.py             MODIFY  add signal attribution; drop old brief cache methods; expose .connection
│   └── repos/
│       ├── __init__.py       CREATE  re-exports
│       ├── project_repo.py   CREATE  async CRUD + uniqueness check
│       ├── task_repo.py      CREATE  async CRUD + filter queries + auto-stamp completed_at
│       └── brief_cache_repo.py CREATE async get/put/delete per horizon
├── agents/
│   ├── base.py               MODIFY  LeadAgentProtocol: synthesize(horizon) -> Brief
│   ├── codebase_agent.py     MODIFY  docstring annotation only (gating is in app.py)
│   ├── lead_agent.py         REWRITE horizon dispatcher + context builder + prompt composer
│   └── prompts/
│       ├── __init__.py       CREATE  loader for the persona file
│       └── irma_persona.md   CREATE  the persona system prompt
├── routers/
│   ├── projects.py           CREATE  CRUD endpoints
│   ├── tasks.py              CREATE  CRUD + /complete shortcut
│   ├── brief.py              CREATE  /brief/today|week|month|overview
│   ├── signals.py            MODIFY  run_refresh stops calling synthesize; invalidates brief_cache
│   └── standup.py            DELETE
├── runtime/
│   └── scheduler.py          (untouched — period stays at IRMA_REFRESH_MINUTES)
├── config.py                 MODIFY  add irma_codebase_agent_enabled
└── app.py                    MODIFY  register new routers, drop standup, gate CodebaseAgent,
                                      construct ProjectRepo/TaskRepo/BriefCacheRepo, pass to LeadAgent

services/api/.env.example     MODIFY  IRMA_CODEBASE_AGENT_ENABLED=false

services/api/tests/
├── conftest.py               MODIFY  add db/store/repo fixtures, sample projects + tasks
├── test_project_model.py     CREATE
├── test_task_model.py        CREATE
├── test_brief_model.py       CREATE
├── test_migrations.py        CREATE
├── test_project_repo.py      CREATE
├── test_task_repo.py         CREATE
├── test_brief_cache_repo.py  CREATE
├── test_signal_attribution.py CREATE
├── test_lead_agent_horizons.py CREATE
├── test_routers_projects.py  CREATE
├── test_routers_tasks.py     CREATE
├── test_routers_brief.py     CREATE
└── test_brief_parse.py       DELETE (covers the dead StandupBrief shape)

apps/desktop/src/
├── lib/
│   ├── types.ts              MODIFY  add Project/Task/Brief types; remove StandupBrief
│   └── api.ts                MODIFY  typed functions for new endpoints; drop fetchStandup
├── main/
│   ├── App.tsx               REWRITE header + tab state; mounts BriefView | ProjectsView
│   ├── StandupView.tsx       DELETE
│   ├── mockBrief.ts          DELETE
│   ├── brief/
│   │   ├── BriefView.tsx     CREATE
│   │   ├── HorizonTabs.tsx   CREATE
│   │   ├── FocusList.tsx     CREATE
│   │   ├── ConflictList.tsx  CREATE  (replaces components/ConflictList; brief-shaped)
│   │   └── Narrative.tsx     CREATE  (replaces components/Narrative; brief-shaped)
│   └── projects/
│       ├── ProjectsView.tsx  CREATE
│       ├── ProjectList.tsx   CREATE
│       ├── ProjectDetail.tsx CREATE
│       ├── ProjectForm.tsx   CREATE
│       ├── TaskList.tsx      CREATE
│       ├── TaskRow.tsx       CREATE
│       └── TaskAddRow.tsx    CREATE

CLAUDE.md                     MODIFY  §5 (abstractions), §6 (API surface), §9 (phases)
```

---

## Phase 0 — Schema migration

One task. Strictly additive: existing `signals` rows stay valid; existing `briefs` table is dropped because the cache-key model is incompatible (`signal_set_hash` → `horizon`).

### Task 0.1: Extend `ensure_schema` with new tables and a `signals.project_id` column

**Files:**
- Modify: `services/api/src/irma_api/store/migrations.py`
- Create: `services/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_migrations.py`:

```python
"""Schema migration: idempotent, additive, exposes the new tables/columns."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from irma_api.store.migrations import ensure_schema


@pytest.mark.asyncio
async def test_ensure_schema_creates_all_tables(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys=ON")
        await ensure_schema(conn)

        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {r[0] for r in await cur.fetchall()}

    assert {"signals", "project", "task", "brief_cache"} <= names
    assert "briefs" not in names  # old cache dropped


@pytest.mark.asyncio
async def test_signals_has_project_id_column(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(signals)")
        cols = {r[1] for r in await cur.fetchall()}
    assert "project_id" in cols


@pytest.mark.asyncio
async def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        await ensure_schema(conn)  # second call must not raise
        cur = await conn.execute("SELECT COUNT(*) FROM project")
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_ensure_schema_adds_project_id_to_existing_signals_db(
    tmp_path: Path,
) -> None:
    """Simulates upgrading a pre-existing DB created from the old schema."""
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        # Old-shape signals table without project_id.
        await conn.execute(
            """
            CREATE TABLE signals (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                source        TEXT    NOT NULL,
                kind          TEXT    NOT NULL,
                title         TEXT    NOT NULL,
                detail        TEXT    NOT NULL DEFAULT '',
                ts            TEXT    NOT NULL,
                meta_json     TEXT    NOT NULL DEFAULT '{}',
                hash_key      TEXT    NOT NULL UNIQUE,
                collected_at  TEXT    NOT NULL
            )
            """
        )
        await conn.execute(
            "INSERT INTO signals "
            "(source, kind, title, detail, ts, meta_json, hash_key, collected_at) "
            "VALUES ('calendar','event','old','','2026-01-01T00:00:00Z','{}','x','now')"
        )
        await conn.commit()

        await ensure_schema(conn)  # upgrade in place

        cur = await conn.execute("PRAGMA table_info(signals)")
        cols = {r[1] for r in await cur.fetchall()}
        assert "project_id" in cols

        # Existing row preserved, project_id NULL.
        cur = await conn.execute("SELECT title, project_id FROM signals")
        rows = await cur.fetchall()
    assert rows == [("old", None)]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_migrations.py -v
```

Expected: 4 failures or errors — the schema does not yet contain the new tables, `briefs` still exists, `project_id` column missing.

- [ ] **Step 3: Rewrite `migrations.py`**

Overwrite `services/api/src/irma_api/store/migrations.py`:

```python
"""Idempotent schema bootstrap. Called once during app lifespan startup.

Strategy: additive `CREATE TABLE IF NOT EXISTS` for all tables, plus a
single targeted `ALTER TABLE signals ADD COLUMN project_id` guarded by a
column-existence check so re-runs are safe. The old `briefs` table is
dropped explicitly because its cache key (`signal_set_hash`) is
incompatible with the new horizon-keyed `brief_cache`.
"""

from __future__ import annotations

import aiosqlite

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS signals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT    NOT NULL,
        kind          TEXT    NOT NULL,
        title         TEXT    NOT NULL,
        detail        TEXT    NOT NULL DEFAULT '',
        ts            TEXT    NOT NULL,
        meta_json     TEXT    NOT NULL DEFAULT '{}',
        hash_key      TEXT    NOT NULL UNIQUE,
        collected_at  TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signals_source_kind ON signals(source, kind)",
    "CREATE INDEX IF NOT EXISTS idx_signals_ts          ON signals(ts)",
    """
    CREATE TABLE IF NOT EXISTS project (
        id                 TEXT    PRIMARY KEY,
        name               TEXT    NOT NULL,
        name_lower         TEXT    NOT NULL UNIQUE,
        description        TEXT    NOT NULL DEFAULT '',
        status             TEXT    NOT NULL DEFAULT 'active',
        priority           INTEGER NOT NULL DEFAULT 2,
        calendar_keywords  TEXT    NOT NULL DEFAULT '[]',
        goals              TEXT    NOT NULL DEFAULT '[]',
        target_date        TEXT,
        created_at         TEXT    NOT NULL,
        updated_at         TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_project_status_priority "
    "ON project(status, priority, name_lower)",
    """
    CREATE TABLE IF NOT EXISTS task (
        id                 TEXT    PRIMARY KEY,
        project_id         TEXT    NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
        title              TEXT    NOT NULL,
        notes              TEXT    NOT NULL DEFAULT '',
        status             TEXT    NOT NULL DEFAULT 'todo',
        due_date           TEXT,
        scheduled_for      TEXT,
        estimated_minutes  INTEGER,
        created_at         TEXT    NOT NULL,
        updated_at         TEXT    NOT NULL,
        completed_at       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_project       ON task(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_scheduled     ON task(scheduled_for)",
    "CREATE INDEX IF NOT EXISTS idx_task_due_status    ON task(due_date, status)",
    """
    CREATE TABLE IF NOT EXISTS brief_cache (
        horizon       TEXT PRIMARY KEY
            CHECK (horizon IN ('day','week','month','all')),
        payload_json  TEXT NOT NULL,
        inputs_hash   TEXT NOT NULL,
        computed_at   TEXT NOT NULL
    )
    """,
    "DROP TABLE IF EXISTS briefs",
)


async def _signals_has_project_id(conn: aiosqlite.Connection) -> bool:
    cur = await conn.execute("PRAGMA table_info(signals)")
    return any(row[1] == "project_id" for row in await cur.fetchall())


async def ensure_schema(conn: aiosqlite.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        await conn.execute(statement)

    if not await _signals_has_project_id(conn):
        await conn.execute("ALTER TABLE signals ADD COLUMN project_id TEXT")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signals_project_id "
        "ON signals(project_id)"
    )
    await conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_migrations.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Run the full suite to confirm no regression**

```bash
cd services/api && uv run pytest -q
```

Expected: existing tests still pass (a few unrelated tests may already be red — note them but do not fix here).

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/store/migrations.py services/api/tests/test_migrations.py
git commit -m "$(cat <<'EOF'
feat(api): schema migration for project/task/brief_cache

Adds project, task, brief_cache tables and a nullable signals.project_id
column. Drops the old signal-hash-keyed briefs table.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 1 — Pydantic models

Three tasks. Pure data + validators; no I/O. Each model gets a focused test file.

### Task 1.1: `Project` model with validators

**Files:**
- Create: `services/api/src/irma_api/models/project.py`
- Create: `services/api/tests/test_project_model.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_project_model.py`:

```python
"""Project Pydantic shape: validators, normalization, DTOs."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from irma_api.models.project import (
    Project,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
)


def _now() -> datetime:
    return datetime(2026, 5, 27, 12, 0, 0)


def test_minimal_project_round_trips() -> None:
    p = Project(
        id="p1",
        name="Thesis",
        created_at=_now(),
        updated_at=_now(),
    )
    assert p.status is ProjectStatus.ACTIVE
    assert p.priority == 2
    assert p.calendar_keywords == []
    assert p.goals == []
    assert p.target_date is None


def test_name_is_trimmed_and_length_bounded() -> None:
    p = Project(id="p1", name="  Thesis  ", created_at=_now(), updated_at=_now())
    assert p.name == "Thesis"

    with pytest.raises(ValidationError):
        Project(id="p1", name="", created_at=_now(), updated_at=_now())

    with pytest.raises(ValidationError):
        Project(id="p1", name="x" * 81, created_at=_now(), updated_at=_now())


def test_priority_must_be_in_range() -> None:
    Project(id="p1", name="x", priority=1, created_at=_now(), updated_at=_now())
    Project(id="p1", name="x", priority=3, created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Project(id="p1", name="x", priority=0, created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Project(id="p1", name="x", priority=4, created_at=_now(), updated_at=_now())


def test_calendar_keywords_lowercased_and_deduped() -> None:
    p = Project(
        id="p1",
        name="x",
        calendar_keywords=["Gal", "gal", "  Lab  ", "lab", "ok"],
        created_at=_now(),
        updated_at=_now(),
    )
    assert p.calendar_keywords == ["gal", "lab", "ok"]


def test_calendar_keywords_min_length_enforced() -> None:
    with pytest.raises(ValidationError):
        Project(
            id="p1",
            name="x",
            calendar_keywords=["a"],
            created_at=_now(),
            updated_at=_now(),
        )


def test_project_create_defaults() -> None:
    pc = ProjectCreate(name="Thesis")
    assert pc.status is ProjectStatus.ACTIVE
    assert pc.priority == 2
    assert pc.calendar_keywords == []
    assert pc.goals == []
    assert pc.target_date is None
    assert pc.description == ""


def test_project_update_all_fields_optional() -> None:
    pu = ProjectUpdate()
    assert pu.model_dump(exclude_unset=True) == {}

    pu2 = ProjectUpdate(name="New", target_date=date(2026, 7, 15))
    assert pu2.model_dump(exclude_unset=True) == {
        "name": "New",
        "target_date": date(2026, 7, 15),
    }


def test_status_enum_values_match_spec() -> None:
    assert ProjectStatus.ACTIVE.value == "active"
    assert ProjectStatus.PAUSED.value == "paused"
    assert ProjectStatus.ARCHIVED.value == "archived"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_project_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'irma_api.models.project'`.

- [ ] **Step 3: Write the implementation**

Create `services/api/src/irma_api/models/project.py`:

```python
"""Project entity — manually managed unit grouping goals + calendar keywords."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


def _normalize_keywords(raw: list[str]) -> list[str]:
    """Lowercase, trim, dedupe (preserve first-seen order), enforce min len."""
    seen: dict[str, None] = {}
    for kw in raw:
        if not isinstance(kw, str):
            raise ValueError("calendar_keywords entries must be strings")
        normalized = kw.strip().lower()
        if len(normalized) < 2:
            raise ValueError(f"calendar keyword too short: {kw!r}")
        seen.setdefault(normalized, None)
    return list(seen.keys())


class _ProjectFields(BaseModel):
    """Shared field definitions for Project + ProjectCreate + ProjectUpdate."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    priority: int = Field(default=2, ge=1, le=3)
    calendar_keywords: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    target_date: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("calendar_keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("calendar_keywords must be a list")
        return _normalize_keywords(v)


class Project(_ProjectFields):
    """A persisted Project row."""

    id: str
    created_at: datetime
    updated_at: datetime


class ProjectCreate(_ProjectFields):
    """Incoming payload for `POST /projects`."""


class ProjectUpdate(BaseModel):
    """Partial update for `PATCH /projects/{id}`. Every field optional."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None
    status: ProjectStatus | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    calendar_keywords: list[str] | None = None
    goals: list[str] | None = None
    target_date: date | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("calendar_keywords", mode="before")
    @classmethod
    def _normalize_keywords(cls, v: object) -> object:
        if v is None:
            return None
        if not isinstance(v, list):
            raise ValueError("calendar_keywords must be a list")
        return _normalize_keywords(v)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_project_model.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/models/project.py services/api/tests/test_project_model.py
git commit -m "$(cat <<'EOF'
feat(api): Project Pydantic model with validators

Includes ProjectCreate/Update DTOs, calendar_keywords normalization,
priority bounds, name trim + uniqueness-by-lowercase.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: `Task` model with auto-stamped `completed_at`

**Files:**
- Create: `services/api/src/irma_api/models/task.py`
- Create: `services/api/tests/test_task_model.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_task_model.py`:

```python
"""Task Pydantic shape: validators, status transitions, DTOs."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from irma_api.models.task import (
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    apply_status_transition,
)


def _now() -> datetime:
    return datetime(2026, 5, 27, 12, 0, 0)


def test_minimal_task_round_trips() -> None:
    t = Task(
        id="t1",
        project_id="p1",
        title="Draft results",
        created_at=_now(),
        updated_at=_now(),
    )
    assert t.status is TaskStatus.TODO
    assert t.notes == ""
    assert t.due_date is None
    assert t.scheduled_for is None
    assert t.estimated_minutes is None
    assert t.completed_at is None


def test_title_length_bounds() -> None:
    Task(id="t1", project_id="p1", title="x", created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Task(id="t1", project_id="p1", title="", created_at=_now(), updated_at=_now())
    with pytest.raises(ValidationError):
        Task(
            id="t1",
            project_id="p1",
            title="x" * 201,
            created_at=_now(),
            updated_at=_now(),
        )


def test_estimated_minutes_must_be_positive() -> None:
    Task(
        id="t1",
        project_id="p1",
        title="x",
        estimated_minutes=1,
        created_at=_now(),
        updated_at=_now(),
    )
    with pytest.raises(ValidationError):
        Task(
            id="t1",
            project_id="p1",
            title="x",
            estimated_minutes=0,
            created_at=_now(),
            updated_at=_now(),
        )


def test_due_date_in_past_is_allowed() -> None:
    Task(
        id="t1",
        project_id="p1",
        title="x",
        due_date=date(1999, 1, 1),
        created_at=_now(),
        updated_at=_now(),
    )


def test_apply_status_transition_done_stamps_completed_at() -> None:
    existing = Task(
        id="t1",
        project_id="p1",
        title="x",
        status=TaskStatus.TODO,
        created_at=_now(),
        updated_at=_now(),
    )
    new = apply_status_transition(
        existing,
        new_status=TaskStatus.DONE,
        now=datetime(2026, 6, 1, 10, 0),
    )
    assert new.status is TaskStatus.DONE
    assert new.completed_at == datetime(2026, 6, 1, 10, 0)
    # Originating row unchanged.
    assert existing.completed_at is None


def test_apply_status_transition_unsetting_done_clears_completed_at() -> None:
    existing = Task(
        id="t1",
        project_id="p1",
        title="x",
        status=TaskStatus.DONE,
        completed_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    new = apply_status_transition(
        existing, new_status=TaskStatus.DOING, now=datetime(2026, 6, 1)
    )
    assert new.status is TaskStatus.DOING
    assert new.completed_at is None


def test_apply_status_transition_done_to_done_preserves_completed_at() -> None:
    first = datetime(2026, 5, 1, 9, 0)
    existing = Task(
        id="t1",
        project_id="p1",
        title="x",
        status=TaskStatus.DONE,
        completed_at=first,
        created_at=_now(),
        updated_at=_now(),
    )
    new = apply_status_transition(
        existing, new_status=TaskStatus.DONE, now=datetime(2026, 6, 1)
    )
    assert new.completed_at == first


def test_task_create_defaults() -> None:
    tc = TaskCreate(project_id="p1", title="x")
    assert tc.status is TaskStatus.TODO
    assert tc.due_date is None


def test_task_update_all_fields_optional() -> None:
    tu = TaskUpdate()
    assert tu.model_dump(exclude_unset=True) == {}
    tu2 = TaskUpdate(status=TaskStatus.DOING)
    assert tu2.model_dump(exclude_unset=True) == {"status": TaskStatus.DOING}


def test_status_enum_values_match_spec() -> None:
    assert TaskStatus.TODO.value == "todo"
    assert TaskStatus.DOING.value == "doing"
    assert TaskStatus.DONE.value == "done"
    assert TaskStatus.BLOCKED.value == "blocked"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_task_model.py -v
```

Expected: `ModuleNotFoundError: No module named 'irma_api.models.task'`.

- [ ] **Step 3: Write the implementation**

Create `services/api/src/irma_api/models/task.py`:

```python
"""Task entity — a manually entered work item scoped to a Project."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    BLOCKED = "blocked"


class _TaskFields(BaseModel):
    """Shared field definitions for Task + TaskCreate."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    project_id: str
    title: str = Field(min_length=1, max_length=200)
    notes: str = ""
    status: TaskStatus = TaskStatus.TODO
    due_date: date | None = None
    scheduled_for: date | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class Task(_TaskFields):
    """A persisted Task row."""

    id: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TaskCreate(_TaskFields):
    """Incoming payload for `POST /tasks`."""


class TaskUpdate(BaseModel):
    """Partial update for `PATCH /tasks/{id}`. Every field optional."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = None
    status: TaskStatus | None = None
    due_date: date | None = None
    scheduled_for: date | None = None
    estimated_minutes: int | None = Field(default=None, gt=0)

    @field_validator("title", mode="before")
    @classmethod
    def _trim_title(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


def apply_status_transition(
    task: Task, *, new_status: TaskStatus, now: datetime
) -> Task:
    """Return a copy of `task` with `status` updated and `completed_at`
    auto-stamped (set on transition to DONE, cleared on transition out of
    DONE, preserved on DONE→DONE).
    """
    if task.status is new_status:
        return task.model_copy(update={"status": new_status})

    if new_status is TaskStatus.DONE:
        return task.model_copy(update={"status": new_status, "completed_at": now})

    if task.status is TaskStatus.DONE:
        return task.model_copy(update={"status": new_status, "completed_at": None})

    return task.model_copy(update={"status": new_status})
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_task_model.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/models/task.py services/api/tests/test_task_model.py
git commit -m "$(cat <<'EOF'
feat(api): Task Pydantic model + status-transition helper

Includes TaskCreate/Update DTOs, validators, and apply_status_transition
which auto-stamps/clears completed_at on transitions in and out of DONE.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.3: Rewrite `models/brief.py` — new `Brief` shape, drop `StandupBrief`

**Files:**
- Modify (rewrite): `services/api/src/irma_api/models/brief.py`
- Create: `services/api/tests/test_brief_model.py`
- Delete: `services/api/tests/test_brief_parse.py`

This breaks every caller of `StandupBrief`. We fix the build in Task 2.5 (`SignalStore`), Task 3.4 (`app.py` router wiring), and Task 4.2 (`LeadAgent`). Tests for those layers stay red until then — that is expected.

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_brief_model.py`:

```python
"""Brief Pydantic shape: horizon types, focus item kinds, parsing."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from irma_api.models.brief import (
    Brief,
    FocusItem,
    FocusKind,
    ProjectStatusItem,
)


def _now() -> datetime:
    return datetime(2026, 5, 27, 12, 0, 0)


def test_brief_minimum_required_fields() -> None:
    b = Brief(
        horizon="day",
        generated_at=_now(),
        focus=[],
        project_status=[],
        conflicts=[],
        recommendation="Start with the draft.",
        narrative="",
    )
    assert b.horizon == "day"
    assert b.has_attention_signal is False


def test_horizon_must_be_known_value() -> None:
    Brief(
        horizon="week",
        generated_at=_now(),
        focus=[],
        project_status=[],
        conflicts=[],
        recommendation="ok",
        narrative="",
    )
    with pytest.raises(ValidationError):
        Brief(
            horizon="quarter",
            generated_at=_now(),
            focus=[],
            project_status=[],
            conflicts=[],
            recommendation="ok",
            narrative="",
        )


def test_focus_item_task_kind() -> None:
    fi = FocusItem(
        kind=FocusKind.TASK,
        title="Draft results",
        project_id="p1",
        project_name="Thesis",
        task_id="t1",
        due_date="2026-05-28",
    )
    assert fi.kind is FocusKind.TASK
    assert fi.task_id == "t1"


def test_focus_item_event_kind() -> None:
    fi = FocusItem(
        kind=FocusKind.EVENT,
        title="Meeting with Prof. Gal",
        project_id="p1",
        project_name="Thesis",
        when="2026-05-27T14:00:00Z",
    )
    assert fi.kind is FocusKind.EVENT
    assert fi.task_id is None


def test_has_attention_signal_flips_on_conflicts() -> None:
    b = Brief(
        horizon="day",
        generated_at=_now(),
        focus=[],
        project_status=[],
        conflicts=["MIT block overlaps thesis window"],
        recommendation="ok",
        narrative="",
    )
    assert b.has_attention_signal is True


def test_brief_round_trips_through_json() -> None:
    b = Brief(
        horizon="day",
        generated_at=_now(),
        focus=[
            FocusItem(
                kind=FocusKind.TASK,
                title="x",
                project_id="p1",
                project_name="Thesis",
                task_id="t1",
            ),
        ],
        project_status=[
            ProjectStatusItem(
                project_id="p1",
                project_name="Thesis",
                open_tasks=3,
                done_tasks=1,
                note="on track",
            )
        ],
        conflicts=[],
        recommendation="x",
        narrative="x",
    )
    blob = b.model_dump_json()
    parsed = Brief.model_validate_json(blob)
    assert parsed == b


def test_standup_brief_is_gone() -> None:
    """The old auto-observed brief shape must not be importable anymore."""
    from irma_api.models import brief

    assert not hasattr(brief, "StandupBrief")
```

- [ ] **Step 2: Delete the obsolete `test_brief_parse.py`**

```bash
git rm services/api/tests/test_brief_parse.py
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_brief_model.py -v
```

Expected: `ImportError` for `Brief`/`FocusItem`/`FocusKind`/`ProjectStatusItem`.

- [ ] **Step 4: Rewrite `models/brief.py`**

Overwrite `services/api/src/irma_api/models/brief.py`:

```python
"""Brief — the horizon-aware synthesis output Claude must produce."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Horizon = Literal["day", "week", "month", "all"]


class FocusKind(StrEnum):
    TASK = "task"
    EVENT = "event"


class FocusItem(BaseModel):
    """A single actionable row in the brief: a task to do or an event to attend."""

    model_config = ConfigDict(populate_by_name=True)

    kind: FocusKind
    title: str
    project_id: str | None = None
    project_name: str | None = None
    # Populated when kind == TASK.
    task_id: str | None = None
    due_date: str | None = None
    scheduled_for: str | None = None
    # Populated when kind == EVENT (ISO-8601 string; Claude returns a string).
    when: str | None = None
    note: str = ""


class ProjectStatusItem(BaseModel):
    """Per-project rollup row, salient for week/month/overview briefs."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str
    project_name: str
    open_tasks: int = 0
    done_tasks: int = 0
    days_to_target: int | None = None
    note: str = ""


class Brief(BaseModel):
    """A horizon-aware brief in Irma's voice."""

    model_config = ConfigDict(frozen=False, populate_by_name=True)

    horizon: Horizon
    generated_at: datetime
    focus: list[FocusItem] = Field(default_factory=list)
    project_status: list[ProjectStatusItem] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    recommendation: str
    narrative: str

    @property
    def has_attention_signal(self) -> bool:
        """True when the sprite should flip to `alert`."""
        return bool(self.conflicts)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_brief_model.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Confirm the rest of the suite is now red as expected**

```bash
cd services/api && uv run pytest -q || true
```

Expected: import errors in `agents/lead_agent.py`, `agents/base.py`, `routers/standup.py`, `store/sqlite.py`, `routers/signals.py` — all referencing `StandupBrief`. These are fixed in subsequent tasks. Do not patch them here.

- [ ] **Step 7: Commit**

```bash
git add services/api/src/irma_api/models/brief.py services/api/tests/test_brief_model.py services/api/tests/test_brief_parse.py
git commit -m "$(cat <<'EOF'
feat(api): replace StandupBrief with horizon-aware Brief shape

New Brief has horizon, focus[], project_status[], conflicts[],
recommendation, narrative. FocusItem unifies tasks and events.
Callers (LeadAgent, store, routers) are red until Tasks 2.5/3.4/4.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — Store layer

Six tasks. Establishes errors, shared test fixtures, three new repos, and updates `SignalStore` to attribute calendar signals to projects + drop the dead brief-cache methods.

### Task 2.1: `store/errors.py`

**Files:**
- Create: `services/api/src/irma_api/store/errors.py`

No tests — these are trivial sentinel exception classes; they get covered indirectly by repo tests.

- [ ] **Step 1: Write the file**

Create `services/api/src/irma_api/store/errors.py`:

```python
"""Typed store-layer exceptions. Routers translate to HTTPException."""

from __future__ import annotations


class StoreError(RuntimeError):
    """Base class for all store-layer failures."""


class NotFoundError(StoreError):
    """Raised when a lookup by id returns no row."""

    def __init__(self, entity: str, key: str) -> None:
        super().__init__(f"{entity} not found: {key!r}")
        self.entity = entity
        self.key = key


class ConflictError(StoreError):
    """Raised on uniqueness, FK, or business-rule violations."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
```

- [ ] **Step 2: Commit**

```bash
git add services/api/src/irma_api/store/errors.py
git commit -m "$(cat <<'EOF'
feat(api): typed store-layer error classes

NotFoundError + ConflictError; base StoreError. Routers translate
these to HTTPException 404/409.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.2: Shared test fixtures (`conftest.py`)

**Files:**
- Modify: `services/api/tests/conftest.py`

Adds an in-memory `aiosqlite` connection fixture + a connected `SignalStore` so subsequent tasks share infrastructure instead of re-spelling it.

- [ ] **Step 1: Rewrite `conftest.py`**

Overwrite `services/api/tests/conftest.py`:

```python
"""Shared pytest fixtures.

Provides:
- `_reset_settings_cache` (autouse): clears the @lru_cache on get_settings().
- `db_conn`: a fresh in-memory aiosqlite connection with the schema applied.
- `store`: a connected SignalStore backed by a temp file DB.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from irma_api.store.migrations import ensure_schema
from irma_api.store.sqlite import SignalStore


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from irma_api.config import get_settings

    get_settings.cache_clear()


@pytest_asyncio.fixture
async def db_conn() -> AsyncIterator[aiosqlite.Connection]:
    """Fresh in-memory aiosqlite connection with the schema applied."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = aiosqlite.Row
    await ensure_schema(conn)
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> AsyncIterator[SignalStore]:
    """A connected SignalStore backed by a fresh file DB per test."""
    s = SignalStore(tmp_path / "irma.db")
    await s.connect()
    try:
        yield s
    finally:
        await s.close()
```

- [ ] **Step 2: Sanity check**

```bash
cd services/api && uv run pytest tests/test_migrations.py tests/test_project_model.py tests/test_task_model.py tests/test_brief_model.py -v
```

Expected: all previously-green tests still pass. (`SignalStore` import in the new fixture will succeed because Phase 1 only edited `models/brief.py`; sqlite.py still imports the now-deleted `StandupBrief` symbol — see Step 3.)

- [ ] **Step 3: If `SignalStore` import is red**, stub `store/sqlite.py` to unblock fixtures

The import chain `conftest → store.sqlite → models.brief.StandupBrief` is now broken. Patch `sqlite.py` with a *minimal* stub change (full rewrite lands in Task 2.6):

Open `services/api/src/irma_api/store/sqlite.py` and:

- Replace `from irma_api.models.brief import StandupBrief` with a `pass` placeholder; remove the `--- Briefs ---` section (`get_cached_brief`, `cache_brief`, `invalidate_briefs`).

The minimal patch: delete lines 14 and 115–143 of the original file. The class should end at the end of `_row_to_signal`.

- [ ] **Step 4: Re-run sanity check**

```bash
cd services/api && uv run pytest tests/test_migrations.py tests/test_project_model.py tests/test_task_model.py tests/test_brief_model.py -v
```

Expected: still green. The other tests (signals router etc.) are still red — fixed in later tasks.

- [ ] **Step 5: Commit**

```bash
git add services/api/tests/conftest.py services/api/src/irma_api/store/sqlite.py
git commit -m "$(cat <<'EOF'
test(api): shared db/store fixtures; remove dead StandupBrief refs

conftest gains db_conn + store fixtures for repo/integration tests.
SignalStore stops importing the now-deleted StandupBrief; the old
brief-cache methods are removed (replaced in Task 2.6 by an updated
SignalStore + new BriefCacheRepo).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.3: `ProjectRepo`

**Files:**
- Create: `services/api/src/irma_api/store/repos/__init__.py`
- Create: `services/api/src/irma_api/store/repos/project_repo.py`
- Create: `services/api/tests/test_project_repo.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_project_repo.py`:

```python
"""ProjectRepo: CRUD, uniqueness, status filtering, ordering."""

from __future__ import annotations

from datetime import date

import aiosqlite
import pytest

from irma_api.models.project import ProjectCreate, ProjectStatus, ProjectUpdate
from irma_api.store.errors import ConflictError, NotFoundError
from irma_api.store.repos.project_repo import ProjectRepo


@pytest.mark.asyncio
async def test_create_and_get(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    p = await repo.create(
        ProjectCreate(
            name="Thesis",
            description="Bar-Ilan M.Sc",
            calendar_keywords=["gal", "thesis"],
            goals=["Submit draft by 2026-07-15"],
            target_date=date(2026, 7, 15),
            priority=1,
        )
    )
    assert p.id
    assert p.name == "Thesis"
    assert p.calendar_keywords == ["gal", "thesis"]
    fetched = await repo.get(p.id)
    assert fetched == p


@pytest.mark.asyncio
async def test_create_duplicate_name_case_insensitive_conflicts(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProjectRepo(db_conn)
    await repo.create(ProjectCreate(name="Thesis"))
    with pytest.raises(ConflictError):
        await repo.create(ProjectCreate(name="THESIS"))


@pytest.mark.asyncio
async def test_get_missing_raises_not_found(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    with pytest.raises(NotFoundError):
        await repo.get("nope")


@pytest.mark.asyncio
async def test_list_filters_and_orders_by_priority_then_name(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProjectRepo(db_conn)
    await repo.create(ProjectCreate(name="Zeta", priority=3))
    await repo.create(ProjectCreate(name="Alpha", priority=1))
    await repo.create(ProjectCreate(name="Beta", priority=1))
    paused = await repo.create(ProjectCreate(name="Sidekick", priority=2))
    await repo.update(
        paused.id, ProjectUpdate(status=ProjectStatus.PAUSED)
    )

    active = await repo.list(statuses=[ProjectStatus.ACTIVE])
    assert [p.name for p in active] == ["Alpha", "Beta", "Zeta"]

    paused_list = await repo.list(statuses=[ProjectStatus.PAUSED])
    assert [p.name for p in paused_list] == ["Sidekick"]

    both = await repo.list(statuses=[ProjectStatus.ACTIVE, ProjectStatus.PAUSED])
    assert {p.name for p in both} == {"Alpha", "Beta", "Zeta", "Sidekick"}


@pytest.mark.asyncio
async def test_update_partial(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    p = await repo.create(ProjectCreate(name="Thesis", priority=2))
    updated = await repo.update(
        p.id, ProjectUpdate(priority=1, goals=["Draft", "Defense"])
    )
    assert updated.priority == 1
    assert updated.goals == ["Draft", "Defense"]
    assert updated.name == "Thesis"  # untouched
    assert updated.updated_at >= p.updated_at


@pytest.mark.asyncio
async def test_update_to_duplicate_name_conflicts(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = ProjectRepo(db_conn)
    await repo.create(ProjectCreate(name="Thesis"))
    other = await repo.create(ProjectCreate(name="MIT"))
    with pytest.raises(ConflictError):
        await repo.update(other.id, ProjectUpdate(name="thesis"))


@pytest.mark.asyncio
async def test_delete(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    p = await repo.create(ProjectCreate(name="x"))
    await repo.delete(p.id)
    with pytest.raises(NotFoundError):
        await repo.get(p.id)


@pytest.mark.asyncio
async def test_delete_missing_raises(db_conn: aiosqlite.Connection) -> None:
    repo = ProjectRepo(db_conn)
    with pytest.raises(NotFoundError):
        await repo.delete("nope")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_project_repo.py -v
```

Expected: `ModuleNotFoundError: No module named 'irma_api.store.repos'`.

- [ ] **Step 3: Create `store/repos/__init__.py`**

```python
"""Async DAO classes. Each repo accepts an aiosqlite.Connection."""

from irma_api.store.repos.brief_cache_repo import BriefCacheRepo
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

__all__ = ["BriefCacheRepo", "ProjectRepo", "TaskRepo"]
```

(`BriefCacheRepo` and `TaskRepo` are written in Tasks 2.4/2.5 — keep the import here so the package surface is stable.)

- [ ] **Step 4: Implement `ProjectRepo`**

Create `services/api/src/irma_api/store/repos/project_repo.py`:

```python
"""Async CRUD for the `project` table."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

import aiosqlite

from irma_api.models.project import (
    Project,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
)
from irma_api.store.errors import ConflictError, NotFoundError

_COLUMNS = (
    "id, name, description, status, priority, "
    "calendar_keywords, goals, target_date, created_at, updated_at"
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _row_to_project(row: aiosqlite.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        status=ProjectStatus(row["status"]),
        priority=row["priority"],
        calendar_keywords=json.loads(row["calendar_keywords"]),
        goals=json.loads(row["goals"]),
        target_date=(
            date.fromisoformat(row["target_date"]) if row["target_date"] else None
        ),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class ProjectRepo:
    """Pure data access for `project` rows. No business logic."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(self, data: ProjectCreate) -> Project:
        now = _now()
        pid = str(uuid.uuid4())
        try:
            await self._conn.execute(
                f"""
                INSERT INTO project ({_COLUMNS}, name_lower)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    data.name,
                    data.description,
                    data.status.value,
                    data.priority,
                    json.dumps(data.calendar_keywords),
                    json.dumps(data.goals),
                    data.target_date.isoformat() if data.target_date else None,
                    now.isoformat(),
                    now.isoformat(),
                    data.name.lower(),
                ),
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise ConflictError(f"project name already exists: {data.name!r}") from exc
        return await self.get(pid)

    async def get(self, project_id: str) -> Project:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM project WHERE id = ?", (project_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("project", project_id)
        return _row_to_project(row)

    async def list(
        self, statuses: Iterable[ProjectStatus] | None = None
    ) -> list[Project]:
        statuses = list(statuses) if statuses is not None else [ProjectStatus.ACTIVE]
        placeholders = ", ".join("?" * len(statuses))
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM project "
            f"WHERE status IN ({placeholders}) "
            "ORDER BY priority ASC, name_lower ASC",
            tuple(s.value for s in statuses),
        )
        return [_row_to_project(r) for r in await cur.fetchall()]

    async def update(self, project_id: str, patch: ProjectUpdate) -> Project:
        existing = await self.get(project_id)
        updates: dict[str, Any] = patch.model_dump(exclude_unset=True)
        if not updates:
            return existing

        # Special handling for fields with on-disk transforms.
        sets: list[str] = []
        params: list[object] = []
        for key, value in updates.items():
            if key == "name":
                sets += ["name = ?", "name_lower = ?"]
                params += [value, value.lower()]
            elif key in ("calendar_keywords", "goals"):
                sets.append(f"{key} = ?")
                params.append(json.dumps(value))
            elif key == "status":
                sets.append("status = ?")
                params.append(value.value if isinstance(value, ProjectStatus) else value)
            elif key == "target_date":
                sets.append("target_date = ?")
                params.append(value.isoformat() if value else None)
            else:
                sets.append(f"{key} = ?")
                params.append(value)

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(project_id)

        try:
            await self._conn.execute(
                f"UPDATE project SET {', '.join(sets)} WHERE id = ?", params
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise ConflictError("project name conflict on update") from exc
        return await self.get(project_id)

    async def delete(self, project_id: str) -> None:
        cur = await self._conn.execute(
            "DELETE FROM project WHERE id = ?", (project_id,)
        )
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("project", project_id)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_project_repo.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/store/repos/__init__.py services/api/src/irma_api/store/repos/project_repo.py services/api/tests/test_project_repo.py
git commit -m "$(cat <<'EOF'
feat(api): ProjectRepo async CRUD

create/get/list/update/delete with case-insensitive name uniqueness,
priority+name ordering, status filtering. Raises NotFoundError /
ConflictError; routers translate to 404/409.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.4: `TaskRepo`

**Files:**
- Create: `services/api/src/irma_api/store/repos/task_repo.py`
- Create: `services/api/tests/test_task_repo.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_task_repo.py`:

```python
"""TaskRepo: CRUD, filters, ordering, status auto-stamp, FK enforcement."""

from __future__ import annotations

from datetime import date, datetime

import aiosqlite
import pytest

from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate, TaskStatus, TaskUpdate
from irma_api.store.errors import ConflictError, NotFoundError
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo


async def _make_project(db_conn: aiosqlite.Connection, name: str = "P") -> str:
    repo = ProjectRepo(db_conn)
    p = await repo.create(ProjectCreate(name=name))
    return p.id


@pytest.mark.asyncio
async def test_create_and_get(db_conn: aiosqlite.Connection) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(
        TaskCreate(
            project_id=pid,
            title="Draft results",
            due_date=date(2026, 5, 28),
            scheduled_for=date(2026, 5, 27),
            estimated_minutes=90,
        )
    )
    assert t.id
    assert t.status is TaskStatus.TODO
    assert t.completed_at is None
    fetched = await repo.get(t.id)
    assert fetched == t


@pytest.mark.asyncio
async def test_create_with_missing_project_raises_not_found(
    db_conn: aiosqlite.Connection,
) -> None:
    repo = TaskRepo(db_conn)
    with pytest.raises(NotFoundError):
        await repo.create(TaskCreate(project_id="nope", title="x"))


@pytest.mark.asyncio
async def test_list_filters_by_project(db_conn: aiosqlite.Connection) -> None:
    a = await _make_project(db_conn, "A")
    b = await _make_project(db_conn, "B")
    repo = TaskRepo(db_conn)
    await repo.create(TaskCreate(project_id=a, title="A1"))
    await repo.create(TaskCreate(project_id=b, title="B1"))
    out = await repo.list(project_id=a)
    assert [t.title for t in out] == ["A1"]


@pytest.mark.asyncio
async def test_list_filters_by_status_and_window(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    await repo.create(
        TaskCreate(project_id=pid, title="today",
                   scheduled_for=date(2026, 5, 27))
    )
    await repo.create(
        TaskCreate(project_id=pid, title="next-week",
                   scheduled_for=date(2026, 6, 3))
    )
    today_only = await repo.list(
        project_id=pid,
        scheduled_from=date(2026, 5, 27),
        scheduled_to=date(2026, 5, 27),
    )
    assert [t.title for t in today_only] == ["today"]

    done = await repo.list(project_id=pid, statuses=[TaskStatus.DONE])
    assert done == []


@pytest.mark.asyncio
async def test_list_orders_by_due_then_scheduled_then_created(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    later = await repo.create(
        TaskCreate(project_id=pid, title="due-later",
                   due_date=date(2026, 6, 10))
    )
    sooner = await repo.create(
        TaskCreate(project_id=pid, title="due-sooner",
                   due_date=date(2026, 6, 1))
    )
    no_due = await repo.create(TaskCreate(project_id=pid, title="no-due"))
    out = await repo.list(project_id=pid)
    assert [t.id for t in out] == [sooner.id, later.id, no_due.id]


@pytest.mark.asyncio
async def test_update_status_done_stamps_completed_at(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(TaskCreate(project_id=pid, title="x"))
    updated = await repo.update(t.id, TaskUpdate(status=TaskStatus.DONE))
    assert updated.status is TaskStatus.DONE
    assert isinstance(updated.completed_at, datetime)


@pytest.mark.asyncio
async def test_update_status_out_of_done_clears_completed_at(
    db_conn: aiosqlite.Connection,
) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(TaskCreate(project_id=pid, title="x"))
    await repo.update(t.id, TaskUpdate(status=TaskStatus.DONE))
    re_open = await repo.update(t.id, TaskUpdate(status=TaskStatus.TODO))
    assert re_open.completed_at is None


@pytest.mark.asyncio
async def test_delete(db_conn: aiosqlite.Connection) -> None:
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    t = await repo.create(TaskCreate(project_id=pid, title="x"))
    await repo.delete(t.id)
    with pytest.raises(NotFoundError):
        await repo.get(t.id)


@pytest.mark.asyncio
async def test_count_open_blocks_project_delete(
    db_conn: aiosqlite.Connection,
) -> None:
    """ProjectRepo.delete uses TaskRepo.count_non_done_for_project to decide."""
    pid = await _make_project(db_conn)
    repo = TaskRepo(db_conn)
    await repo.create(TaskCreate(project_id=pid, title="open"))
    await repo.create(
        TaskCreate(project_id=pid, title="closed", status=TaskStatus.DONE)
    )
    assert await repo.count_non_done_for_project(pid) == 1


@pytest.mark.asyncio
async def test_project_delete_with_attached_tasks_raises_conflict(
    db_conn: aiosqlite.Connection,
) -> None:
    """Via the FK ON DELETE RESTRICT — sqlite raises IntegrityError."""
    pid = await _make_project(db_conn)
    trepo = TaskRepo(db_conn)
    await trepo.create(TaskCreate(project_id=pid, title="x"))
    prepo = ProjectRepo(db_conn)
    with pytest.raises(ConflictError):
        await prepo.delete(pid)
```

The last test requires `ProjectRepo.delete` to translate `IntegrityError → ConflictError`. Update it accordingly when implementing — see Step 3.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_task_repo.py -v
```

Expected: `ModuleNotFoundError: No module named 'irma_api.store.repos.task_repo'`.

- [ ] **Step 3: Patch `ProjectRepo.delete` to translate FK violation**

Open `services/api/src/irma_api/store/repos/project_repo.py` and replace `delete`:

```python
    async def delete(self, project_id: str) -> None:
        try:
            cur = await self._conn.execute(
                "DELETE FROM project WHERE id = ?", (project_id,)
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise ConflictError(
                "cannot delete project with attached tasks; archive instead"
            ) from exc
        if cur.rowcount == 0:
            raise NotFoundError("project", project_id)
```

- [ ] **Step 4: Implement `TaskRepo`**

Create `services/api/src/irma_api/store/repos/task_repo.py`:

```python
"""Async CRUD for the `task` table."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

import aiosqlite

from irma_api.models.task import (
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate,
    apply_status_transition,
)
from irma_api.store.errors import ConflictError, NotFoundError

_COLUMNS = (
    "id, project_id, title, notes, status, due_date, scheduled_for, "
    "estimated_minutes, created_at, updated_at, completed_at"
)


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _row_to_task(row: aiosqlite.Row) -> Task:
    return Task(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        notes=row["notes"],
        status=TaskStatus(row["status"]),
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        scheduled_for=(
            date.fromisoformat(row["scheduled_for"]) if row["scheduled_for"] else None
        ),
        estimated_minutes=row["estimated_minutes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=(
            datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
        ),
    )


class TaskRepo:
    """Pure data access for `task` rows."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def create(self, data: TaskCreate) -> Task:
        now = _now()
        tid = str(uuid.uuid4())
        try:
            await self._conn.execute(
                f"""
                INSERT INTO task ({_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    tid,
                    data.project_id,
                    data.title,
                    data.notes,
                    data.status.value,
                    data.due_date.isoformat() if data.due_date else None,
                    data.scheduled_for.isoformat() if data.scheduled_for else None,
                    data.estimated_minutes,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            await self._conn.commit()
        except aiosqlite.IntegrityError as exc:
            raise NotFoundError("project", data.project_id) from exc
        return await self.get(tid)

    async def get(self, task_id: str) -> Task:
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM task WHERE id = ?", (task_id,)
        )
        row = await cur.fetchone()
        if row is None:
            raise NotFoundError("task", task_id)
        return _row_to_task(row)

    async def list(
        self,
        *,
        project_id: str | None = None,
        statuses: Iterable[TaskStatus] | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
        due_before: date | None = None,
    ) -> list[Task]:
        where: list[str] = []
        params: list[object] = []
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        if statuses is not None:
            statuses_list = list(statuses)
            placeholders = ", ".join("?" * len(statuses_list))
            where.append(f"status IN ({placeholders})")
            params.extend(s.value for s in statuses_list)
        if scheduled_from is not None:
            where.append("scheduled_for >= ?")
            params.append(scheduled_from.isoformat())
        if scheduled_to is not None:
            where.append("scheduled_for <= ?")
            params.append(scheduled_to.isoformat())
        if due_before is not None:
            where.append("due_date <= ?")
            params.append(due_before.isoformat())

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        # Order: due_date NULLS LAST, scheduled_for NULLS LAST, created_at
        sql = (
            f"SELECT {_COLUMNS} FROM task {clause} "
            "ORDER BY due_date IS NULL, due_date, "
            "scheduled_for IS NULL, scheduled_for, created_at"
        )
        cur = await self._conn.execute(sql, params)
        return [_row_to_task(r) for r in await cur.fetchall()]

    async def update(self, task_id: str, patch: TaskUpdate) -> Task:
        existing = await self.get(task_id)
        updates: dict[str, Any] = patch.model_dump(exclude_unset=True)
        if not updates:
            return existing

        new_status = updates.pop("status", None)
        if new_status is not None:
            transitioned = apply_status_transition(
                existing, new_status=TaskStatus(new_status), now=_now()
            )
            updates["status"] = transitioned.status.value
            updates["completed_at"] = (
                transitioned.completed_at.isoformat()
                if transitioned.completed_at
                else None
            )

        sets: list[str] = []
        params: list[object] = []
        for key, value in updates.items():
            if key in ("due_date", "scheduled_for"):
                sets.append(f"{key} = ?")
                params.append(value.isoformat() if value else None)
            else:
                sets.append(f"{key} = ?")
                params.append(value)
        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(task_id)

        await self._conn.execute(
            f"UPDATE task SET {', '.join(sets)} WHERE id = ?", params
        )
        await self._conn.commit()
        return await self.get(task_id)

    async def delete(self, task_id: str) -> None:
        cur = await self._conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
        await self._conn.commit()
        if cur.rowcount == 0:
            raise NotFoundError("task", task_id)

    async def count_non_done_for_project(self, project_id: str) -> int:
        cur = await self._conn.execute(
            "SELECT COUNT(*) AS n FROM task "
            "WHERE project_id = ? AND status != 'done'",
            (project_id,),
        )
        row = await cur.fetchone()
        return int(row["n"]) if row else 0
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_task_repo.py tests/test_project_repo.py -v
```

Expected: all task + project repo tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/store/repos/task_repo.py services/api/tests/test_task_repo.py services/api/src/irma_api/store/repos/project_repo.py
git commit -m "$(cat <<'EOF'
feat(api): TaskRepo async CRUD + project-delete FK guard

Task list ordering: due_date NULLS LAST → scheduled_for NULLS LAST →
created_at. Status updates route through apply_status_transition so
completed_at auto-stamps. ProjectRepo.delete now translates the FK
ON DELETE RESTRICT violation to ConflictError.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.5: `BriefCacheRepo`

**Files:**
- Create: `services/api/src/irma_api/store/repos/brief_cache_repo.py`
- Create: `services/api/tests/test_brief_cache_repo.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_brief_cache_repo.py`:

```python
"""BriefCacheRepo: per-horizon get/put/delete and clear-all."""

from __future__ import annotations

from datetime import datetime

import aiosqlite
import pytest

from irma_api.models.brief import Brief
from irma_api.store.repos.brief_cache_repo import BriefCacheRepo


def _brief(horizon: str = "day", note: str = "x") -> Brief:
    return Brief(
        horizon=horizon,
        generated_at=datetime(2026, 5, 27, 12, 0, 0),
        focus=[],
        project_status=[],
        conflicts=[],
        recommendation=note,
        narrative="",
    )


@pytest.mark.asyncio
async def test_miss_returns_none(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    assert await repo.get("day", inputs_hash="h1") is None


@pytest.mark.asyncio
async def test_put_then_hit(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    b = _brief("day", "today")
    await repo.put("day", inputs_hash="h1", brief=b)
    assert await repo.get("day", inputs_hash="h1") == b


@pytest.mark.asyncio
async def test_hash_mismatch_is_a_miss(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    await repo.put("day", inputs_hash="h1", brief=_brief("day"))
    assert await repo.get("day", inputs_hash="h2") is None


@pytest.mark.asyncio
async def test_put_overwrites(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    await repo.put("day", inputs_hash="h1", brief=_brief("day", "first"))
    await repo.put("day", inputs_hash="h2", brief=_brief("day", "second"))
    hit = await repo.get("day", inputs_hash="h2")
    assert hit is not None
    assert hit.recommendation == "second"


@pytest.mark.asyncio
async def test_clear_all(db_conn: aiosqlite.Connection) -> None:
    repo = BriefCacheRepo(db_conn)
    for h in ("day", "week", "month", "all"):
        await repo.put(h, inputs_hash="h", brief=_brief(h))
    await repo.clear()
    for h in ("day", "week", "month", "all"):
        assert await repo.get(h, inputs_hash="h") is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_brief_cache_repo.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `BriefCacheRepo`**

Create `services/api/src/irma_api/store/repos/brief_cache_repo.py`:

```python
"""Per-horizon brief cache. One row per horizon; replace-on-write."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from irma_api.models.brief import Brief, Horizon


class BriefCacheRepo:
    """A tiny key/value layer keyed on `horizon`."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get(self, horizon: Horizon, *, inputs_hash: str) -> Brief | None:
        cur = await self._conn.execute(
            "SELECT payload_json, inputs_hash FROM brief_cache WHERE horizon = ?",
            (horizon,),
        )
        row = await cur.fetchone()
        if row is None or row["inputs_hash"] != inputs_hash:
            return None
        return Brief.model_validate_json(row["payload_json"])

    async def put(
        self, horizon: Horizon, *, inputs_hash: str, brief: Brief
    ) -> None:
        await self._conn.execute(
            """
            INSERT INTO brief_cache (horizon, payload_json, inputs_hash, computed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(horizon) DO UPDATE SET
                payload_json = excluded.payload_json,
                inputs_hash  = excluded.inputs_hash,
                computed_at  = excluded.computed_at
            """,
            (
                horizon,
                brief.model_dump_json(),
                inputs_hash,
                datetime.now(UTC).isoformat(),
            ),
        )
        await self._conn.commit()

    async def clear(self) -> None:
        await self._conn.execute("DELETE FROM brief_cache")
        await self._conn.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_brief_cache_repo.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/store/repos/brief_cache_repo.py services/api/tests/test_brief_cache_repo.py
git commit -m "$(cat <<'EOF'
feat(api): BriefCacheRepo (per-horizon brief cache)

get/put/clear keyed on horizon, with inputs_hash gating cache hits.
Used by LeadAgent (Task 4.2) and invalidated by /refresh (Task 5.x).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.6: Update `SignalStore` — expose `.connection`, attribute calendar signals to projects

**Files:**
- Modify: `services/api/src/irma_api/store/sqlite.py`
- Create: `services/api/tests/test_signal_attribution.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_signal_attribution.py`:

```python
"""Calendar signals get attributed to projects via keyword match at write."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from irma_api.models.project import ProjectCreate, ProjectStatus
from irma_api.models.signal import Signal
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.sqlite import SignalStore


async def _signal(title: str, *, source: str = "calendar") -> Signal:
    return Signal(
        source=source,
        kind="event",
        title=title,
        detail="",
        ts=datetime.now(UTC),
        meta={},
    )


@pytest.mark.asyncio
async def test_calendar_signal_attributes_via_keyword(
    store: SignalStore,
) -> None:
    prepo = ProjectRepo(store.connection)
    await prepo.create(ProjectCreate(name="Thesis", calendar_keywords=["gal"]))
    sig = await _signal("Meeting with Prof. Gal")
    await store.upsert_signals([sig])
    rows = await store.connection.execute_fetchall(
        "SELECT title, project_id FROM signals"
    )
    rows = list(rows)
    assert len(rows) == 1
    assert rows[0]["project_id"] is not None


@pytest.mark.asyncio
async def test_codebase_signal_is_never_attributed(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    await prepo.create(ProjectCreate(name="Thesis", calendar_keywords=["thesis"]))
    sig = await _signal("3 commits in thesis", source="codebase")
    await store.upsert_signals([sig])
    rows = list(await store.connection.execute_fetchall(
        "SELECT project_id FROM signals"
    ))
    assert rows[0]["project_id"] is None


@pytest.mark.asyncio
async def test_no_match_yields_null_project(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    await prepo.create(ProjectCreate(name="Thesis", calendar_keywords=["gal"]))
    sig = await _signal("Unrelated event")
    await store.upsert_signals([sig])
    rows = list(await store.connection.execute_fetchall(
        "SELECT project_id FROM signals"
    ))
    assert rows[0]["project_id"] is None


@pytest.mark.asyncio
async def test_multi_match_picks_higher_priority(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    low = await prepo.create(
        ProjectCreate(name="LowP", priority=3, calendar_keywords=["lecture"])
    )
    high = await prepo.create(
        ProjectCreate(name="HighP", priority=1, calendar_keywords=["lecture"])
    )
    sig = await _signal("Lecture today")
    await store.upsert_signals([sig])
    rows = list(await store.connection.execute_fetchall(
        "SELECT project_id FROM signals"
    ))
    assert rows[0]["project_id"] == high.id
    assert rows[0]["project_id"] != low.id


@pytest.mark.asyncio
async def test_archived_project_is_not_matched(store: SignalStore) -> None:
    prepo = ProjectRepo(store.connection)
    p = await prepo.create(
        ProjectCreate(name="X", calendar_keywords=["lab"])
    )
    await prepo.update(
        p.id,
        __import__("irma_api.models.project", fromlist=["ProjectUpdate"])
        .ProjectUpdate(status=ProjectStatus.ARCHIVED),
    )
    sig = await _signal("Lab meeting")
    await store.upsert_signals([sig])
    rows = list(await store.connection.execute_fetchall(
        "SELECT project_id FROM signals"
    ))
    assert rows[0]["project_id"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_signal_attribution.py -v
```

Expected: `AttributeError: 'SignalStore' object has no attribute 'connection'` (or attribution returns None on calendar signals).

- [ ] **Step 3: Update `SignalStore`**

Open `services/api/src/irma_api/store/sqlite.py` and:

1. Add a public `connection` property exposing `_require()`.
2. Inline-attribute calendar signals during `upsert_signals` by joining against `project`.

Replace the existing file with:

```python
"""Async SQLite-backed persistence: signals (with project attribution)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from irma_api.models.signal import Signal
from irma_api.store.migrations import ensure_schema


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def compute_signal_set_hash(signals: Iterable[Signal]) -> str:
    """Stable hash over a set of signals — order-independent."""
    hashes = sorted(s.hash_key() for s in signals)
    blob = "\n".join(hashes).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class SignalStore:
    """Owns a single aiosqlite connection for the process lifetime."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = aiosqlite.Row
        await ensure_schema(self._conn)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def connection(self) -> aiosqlite.Connection:
        """Expose the underlying connection so repos can share it."""
        return self._require()

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SignalStore not connected — call .connect() first")
        return self._conn

    # --- Signals -------------------------------------------------------------

    async def upsert_signals(self, signals: list[Signal]) -> int:
        if not signals:
            return 0
        conn = self._require()
        active_projects = await self._fetch_active_projects()
        rows = [
            (
                s.source,
                s.kind,
                s.title,
                s.detail,
                s.ts.isoformat(),
                json.dumps(s.meta, sort_keys=True, default=str),
                s.hash_key(),
                _iso_now(),
                _match_project_id(s, active_projects),
            )
            for s in signals
        ]
        cur = await conn.executemany(
            """
            INSERT OR IGNORE INTO signals
                (source, kind, title, detail, ts, meta_json, hash_key,
                 collected_at, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await conn.commit()
        return cur.rowcount or 0

    async def latest_signals(self, limit: int = 500) -> list[Signal]:
        conn = self._require()
        cur = await conn.execute(
            "SELECT source, kind, title, detail, ts, meta_json "
            "FROM signals ORDER BY datetime(ts) DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_signal(r) for r in await cur.fetchall()]

    async def _fetch_active_projects(self) -> list[tuple[str, list[str]]]:
        """Return [(project_id, keywords_lowercased)] for active projects,
        ordered by (priority ASC, name_lower ASC) so first-match is deterministic.
        """
        conn = self._require()
        cur = await conn.execute(
            "SELECT id, calendar_keywords FROM project "
            "WHERE status = 'active' "
            "ORDER BY priority ASC, name_lower ASC"
        )
        out: list[tuple[str, list[str]]] = []
        for row in await cur.fetchall():
            kws = json.loads(row["calendar_keywords"]) or []
            out.append((row["id"], [str(k).lower() for k in kws]))
        return out

    @staticmethod
    def _row_to_signal(row: aiosqlite.Row) -> Signal:
        meta_raw = row["meta_json"]
        meta: dict[str, Any] = json.loads(meta_raw) if meta_raw else {}
        return Signal(
            source=row["source"],
            kind=row["kind"],
            title=row["title"],
            detail=row["detail"] or "",
            ts=datetime.fromisoformat(row["ts"]),
            meta=meta,
        )


def _match_project_id(
    sig: Signal, projects: list[tuple[str, list[str]]]
) -> str | None:
    if sig.source != "calendar":
        return None
    haystack = f"{sig.title} {sig.detail}".lower()
    for pid, kws in projects:
        if any(kw in haystack for kw in kws):
            return pid
    return None
```

- [ ] **Step 4: Run the tests**

```bash
cd services/api && uv run pytest tests/test_signal_attribution.py tests/test_project_repo.py tests/test_task_repo.py tests/test_brief_cache_repo.py tests/test_migrations.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/store/sqlite.py services/api/tests/test_signal_attribution.py
git commit -m "$(cat <<'EOF'
feat(api): attribute calendar signals to projects at write time

upsert_signals now joins against active projects and stamps the
first-matching project_id (deterministic by priority+name). Codebase
signals are never attributed. SignalStore exposes .connection so
ProjectRepo/TaskRepo/BriefCacheRepo can share it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — API routers

Four tasks. Adds CRUD endpoints, wires them into `app.py`, deletes `routers/standup.py`. The `/brief/*` endpoints land as a *stub* in this phase (returning `503 synthesis_unavailable`) so the routing surface is testable; the real synthesis lands in Phase 4.

### Task 3.1: `projects` router

**Files:**
- Create: `services/api/src/irma_api/routers/projects.py`
- Create: `services/api/tests/test_routers_projects.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_routers_projects.py`:

```python
"""HTTP surface for /api/v1/projects."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.projects import router as projects_router
from irma_api.store.sqlite import SignalStore


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store
    app.include_router(projects_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
async def test_create_and_list(client: AsyncClient) -> None:
    r = await client.post("/api/v1/projects", json={"name": "Thesis"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Thesis"
    assert body["status"] == "active"

    r = await client.get("/api/v1/projects")
    assert r.status_code == 200
    assert [p["name"] for p in r.json()] == ["Thesis"]


@pytest.mark.asyncio
async def test_create_duplicate_name_409(client: AsyncClient) -> None:
    await client.post("/api/v1/projects", json={"name": "X"})
    r = await client.post("/api/v1/projects", json={"name": "x"})
    assert r.status_code == 409
    assert r.json()["error"] == "conflict"


@pytest.mark.asyncio
async def test_get_404(client: AsyncClient) -> None:
    r = await client.get("/api/v1/projects/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


@pytest.mark.asyncio
async def test_patch(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/projects", json={"name": "X"})).json()
    r = await client.patch(
        f"/api/v1/projects/{created['id']}", json={"priority": 1}
    )
    assert r.status_code == 200
    assert r.json()["priority"] == 1


@pytest.mark.asyncio
async def test_delete(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/projects", json={"name": "X"})).json()
    r = await client.delete(f"/api/v1/projects/{created['id']}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_list_filters_by_status(client: AsyncClient) -> None:
    a = (await client.post("/api/v1/projects", json={"name": "A"})).json()
    await client.post("/api/v1/projects", json={"name": "B"})
    await client.patch(
        f"/api/v1/projects/{a['id']}", json={"status": "archived"}
    )

    active = await client.get("/api/v1/projects?status=active")
    assert [p["name"] for p in active.json()] == ["B"]

    archived = await client.get("/api/v1/projects?status=archived")
    assert [p["name"] for p in archived.json()] == ["A"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_routers_projects.py -v
```

Expected: `ImportError: cannot import name 'router' from 'irma_api.routers.projects'`.

- [ ] **Step 3: Implement the router**

Create `services/api/src/irma_api/routers/projects.py`:

```python
"""HTTP surface for Project CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from irma_api.models.project import (
    Project,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
)
from irma_api.store.errors import ConflictError, NotFoundError
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.sqlite import SignalStore

router = APIRouter(prefix="/projects", tags=["projects"])


def _repo(request: Request) -> ProjectRepo:
    store: SignalStore = request.app.state.store
    return ProjectRepo(store.connection)


def _err(code: int, kind: str, detail: str) -> JSONResponse:
    """Flat error body: {"error": "<machine_code>", "detail": "<human msg>"}."""
    return JSONResponse(status_code=code, content={"error": kind, "detail": detail})


@router.get("", response_model=list[Project])
async def list_projects(
    request: Request,
    status: list[ProjectStatus] | None = None,
) -> list[Project]:
    return await _repo(request).list(statuses=status)


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, payload: ProjectCreate):
    try:
        return await _repo(request).create(payload)
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))


@router.get("/{project_id}", response_model=Project)
async def get_project(request: Request, project_id: str):
    try:
        return await _repo(request).get(project_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))


@router.patch("/{project_id}", response_model=Project)
async def update_project(request: Request, project_id: str, patch: ProjectUpdate):
    try:
        return await _repo(request).update(project_id, patch)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(request: Request, project_id: str):
    try:
        await _repo(request).delete(project_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

The error shape is the flat `{"error": ..., "detail": ...}` body — returned directly from each endpoint via `JSONResponse`, no global exception handler needed. This keeps the router self-contained and matches the test assertions.

And return that from the endpoints (each endpoint catches `NotFoundError`/`ConflictError` and returns `_err(...)`). Update the router accordingly before running tests.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd services/api && uv run pytest tests/test_routers_projects.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/routers/projects.py services/api/tests/test_routers_projects.py
git commit -m "$(cat <<'EOF'
feat(api): /api/v1/projects CRUD router

Wraps ProjectRepo. 404 on missing, 409 on duplicate-name / FK-restrict.
Uses JSONResponse for the flat {error,detail} body shape from the spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: `tasks` router

**Files:**
- Create: `services/api/src/irma_api/routers/tasks.py`
- Create: `services/api/tests/test_routers_tasks.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_routers_tasks.py`:

```python
"""HTTP surface for /api/v1/tasks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.projects import router as projects_router
from irma_api.routers.tasks import router as tasks_router
from irma_api.store.sqlite import SignalStore


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


async def _mk_project(client: AsyncClient, name: str = "P") -> str:
    r = await client.post("/api/v1/projects", json={"name": name})
    return r.json()["id"]


@pytest.mark.asyncio
async def test_create_and_get(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    r = await client.post(
        "/api/v1/tasks",
        json={"project_id": pid, "title": "Draft", "due_date": "2026-05-28"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Draft"
    assert body["status"] == "todo"
    rg = await client.get(f"/api/v1/tasks/{body['id']}")
    assert rg.status_code == 200
    assert rg.json()["id"] == body["id"]


@pytest.mark.asyncio
async def test_create_with_missing_project_404(client: AsyncClient) -> None:
    r = await client.post("/api/v1/tasks", json={"project_id": "nope", "title": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_status_done_sets_completed_at(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    t = (await client.post("/api/v1/tasks", json={"project_id": pid, "title": "x"})).json()
    r = await client.patch(f"/api/v1/tasks/{t['id']}", json={"status": "done"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] is not None


@pytest.mark.asyncio
async def test_complete_shortcut_is_idempotent(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    t = (await client.post("/api/v1/tasks", json={"project_id": pid, "title": "x"})).json()
    r1 = await client.post(f"/api/v1/tasks/{t['id']}/complete")
    r2 = await client.post(f"/api/v1/tasks/{t['id']}/complete")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["completed_at"] == r2.json()["completed_at"]


@pytest.mark.asyncio
async def test_list_filters(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    await client.post(
        "/api/v1/tasks",
        json={"project_id": pid, "title": "today", "scheduled_for": "2026-05-27"},
    )
    await client.post(
        "/api/v1/tasks",
        json={"project_id": pid, "title": "next", "scheduled_for": "2026-06-03"},
    )
    r = await client.get(
        f"/api/v1/tasks?project_id={pid}"
        "&scheduled_from=2026-05-27&scheduled_to=2026-05-27"
    )
    assert [t["title"] for t in r.json()] == ["today"]


@pytest.mark.asyncio
async def test_delete(client: AsyncClient) -> None:
    pid = await _mk_project(client)
    t = (await client.post("/api/v1/tasks", json={"project_id": pid, "title": "x"})).json()
    r = await client.delete(f"/api/v1/tasks/{t['id']}")
    assert r.status_code == 204
    r2 = await client.get(f"/api/v1/tasks/{t['id']}")
    assert r2.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_routers_tasks.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the router**

Create `services/api/src/irma_api/routers/tasks.py`:

```python
"""HTTP surface for Task CRUD."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse

from irma_api.models.task import Task, TaskCreate, TaskStatus, TaskUpdate
from irma_api.store.errors import ConflictError, NotFoundError
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _repo(request: Request) -> TaskRepo:
    store: SignalStore = request.app.state.store
    return TaskRepo(store.connection)


def _err(code: int, kind: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": kind, "detail": detail})


@router.get("", response_model=list[Task])
async def list_tasks(
    request: Request,
    project_id: str | None = None,
    status: list[TaskStatus] | None = Query(default=None),
    scheduled_from: date | None = None,
    scheduled_to: date | None = None,
    due_before: date | None = None,
) -> list[Task]:
    return await _repo(request).list(
        project_id=project_id,
        statuses=status,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
        due_before=due_before,
    )


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(request: Request, payload: TaskCreate):
    try:
        return await _repo(request).create(payload)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))


@router.get("/{task_id}", response_model=Task)
async def get_task(request: Request, task_id: str):
    try:
        return await _repo(request).get(task_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))


@router.patch("/{task_id}", response_model=Task)
async def update_task(request: Request, task_id: str, patch: TaskUpdate):
    try:
        return await _repo(request).update(task_id, patch)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(request: Request, task_id: str):
    try:
        await _repo(request).delete(task_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/complete", response_model=Task)
async def complete_task(request: Request, task_id: str):
    try:
        return await _repo(request).update(
            task_id, TaskUpdate(status=TaskStatus.DONE)
        )
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
```

- [ ] **Step 4: Run the test**

```bash
cd services/api && uv run pytest tests/test_routers_tasks.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/routers/tasks.py services/api/tests/test_routers_tasks.py
git commit -m "$(cat <<'EOF'
feat(api): /api/v1/tasks CRUD router + /{id}/complete shortcut

Wraps TaskRepo. List supports project_id, status (repeatable),
scheduled_from/to, due_before. /complete is idempotent (does not re-stamp
completed_at).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: `brief` router (stub — returns 503; real synthesis lands in Task 4.3)

**Files:**
- Create: `services/api/src/irma_api/routers/brief.py`
- Create: `services/api/tests/test_routers_brief.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_routers_brief.py`:

```python
"""HTTP surface for /api/v1/brief/*.

Phase 3 only verifies routing and the unavailable-503 shape. Phase 4
tests cache hit/miss and synthesis output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from irma_api.routers.brief import router as brief_router
from irma_api.store.sqlite import SignalStore


@pytest_asyncio.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    app.state.store = store
    app.state.lead_agent = None  # explicit: synthesis not configured
    app.include_router(brief_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["today", "week", "month", "overview"])
async def test_horizon_routes_return_503_without_agent(
    client: AsyncClient, path: str
) -> None:
    r = await client.get(f"/api/v1/brief/{path}")
    assert r.status_code == 503
    assert r.json()["error"] == "synthesis_unavailable"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/api && uv run pytest tests/test_routers_brief.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the stub router**

Create `services/api/src/irma_api/routers/brief.py`:

```python
"""HTTP surface for horizon-aware briefs.

The four routes are thin shells that resolve to a single LeadAgent call.
The shell is split out per-horizon so the URLs are self-documenting and
each cache row has a stable, named endpoint.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from irma_api.agents.base import LeadAgentProtocol
from irma_api.models.brief import Brief, Horizon
from irma_api.runtime.state import AgentState, StateBus

router = APIRouter(prefix="/brief", tags=["brief"])


async def _synthesize(request: Request, horizon: Horizon):
    lead_agent: LeadAgentProtocol | None = getattr(
        request.app.state, "lead_agent", None
    )
    if lead_agent is None:
        return JSONResponse(
            status_code=503,
            content={
                "error": "synthesis_unavailable",
                "detail": "LeadAgent not configured",
            },
            headers={"Retry-After": "30"},
        )
    bus: StateBus | None = getattr(request.app.state, "bus", None)
    if bus is not None:
        await bus.publish(AgentState.THINKING)
    try:
        brief = await lead_agent.synthesize(horizon)
    except Exception:
        if bus is not None:
            await bus.publish(AgentState.IDLE)
        raise
    if bus is not None:
        await bus.publish(
            AgentState.ALERT if brief.has_attention_signal else AgentState.IDLE
        )
    return brief


@router.get("/today", response_model=Brief)
async def brief_today(request: Request):
    return await _synthesize(request, "day")


@router.get("/week", response_model=Brief)
async def brief_week(request: Request):
    return await _synthesize(request, "week")


@router.get("/month", response_model=Brief)
async def brief_month(request: Request):
    return await _synthesize(request, "month")


@router.get("/overview", response_model=Brief)
async def brief_overview(request: Request):
    return await _synthesize(request, "all")
```

This depends on `LeadAgentProtocol.synthesize(horizon)`. The protocol still has the old `synthesize(signals)` signature; update it now.

Open `services/api/src/irma_api/agents/base.py` and replace the LeadAgentProtocol block with:

```python
from irma_api.models.brief import Brief, Horizon
# ... Observer protocol unchanged ...

class LeadAgentProtocol(Protocol):
    """Structural type for the horizon-aware synthesis agent."""

    async def synthesize(self, horizon: Horizon) -> Brief:  # pragma: no cover - protocol
        ...
```

Drop the `StandupBrief`/`Signal` imports from this file if unused elsewhere.

- [ ] **Step 4: Run the test**

```bash
cd services/api && uv run pytest tests/test_routers_brief.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/routers/brief.py services/api/tests/test_routers_brief.py services/api/src/irma_api/agents/base.py
git commit -m "$(cat <<'EOF'
feat(api): /api/v1/brief/{today,week,month,overview} routes (stub)

Four named endpoints map to a single LeadAgent.synthesize(horizon).
Returns 503 synthesis_unavailable when LeadAgent is not configured.
LeadAgentProtocol signature updated to synthesize(horizon) -> Brief.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.4: Wire new routers into `app.py`; delete `routers/standup.py`

**Files:**
- Modify: `services/api/src/irma_api/app.py`
- Modify: `services/api/src/irma_api/routers/signals.py`
- Delete: `services/api/src/irma_api/routers/standup.py`

`signals.py` still references `StandupBrief`/`store.invalidate_briefs` and calls `lead_agent.synthesize(signals)`. We patch it to: (a) drop the synth call inside `run_refresh` (briefs are lazy now), (b) invalidate `brief_cache` instead.

- [ ] **Step 1: Update `routers/signals.py`**

Open `services/api/src/irma_api/routers/signals.py` and replace `run_refresh`:

```python
"""Signals + refresh endpoints.

`POST /refresh` runs the observe → upsert cycle and invalidates the
brief cache. Synthesis is lazy: the next GET /brief/<horizon> picks up
the changes.
"""

from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Request

from irma_api.agents.base import Observer
from irma_api.models.signal import Signal
from irma_api.runtime.state import AgentState, StateBus
from irma_api.store.repos.brief_cache_repo import BriefCacheRepo
from irma_api.store.sqlite import SignalStore

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["signals"])


async def gather_signals(observers: list[Observer]) -> list[Signal]:
    results = await asyncio.gather(
        *(o.collect() for o in observers), return_exceptions=True
    )
    out: list[Signal] = []
    for observer, result in zip(observers, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning(
                "refresh.observer_failed",
                observer=getattr(observer, "name", "?"),
                error=str(result),
            )
            continue
        out.extend(result)
    return out


async def run_refresh(
    *,
    store: SignalStore,
    observers: list[Observer],
    bus: StateBus,
) -> dict[str, int]:
    """Observe → upsert → invalidate brief cache → publish terminal state."""
    await bus.publish(AgentState.OBSERVING)
    signals = await gather_signals(observers)
    inserted = await store.upsert_signals(signals)
    await BriefCacheRepo(store.connection).clear()
    await bus.publish(AgentState.IDLE)
    return {"observed": len(signals), "inserted": inserted}


@router.get("/signals")
async def list_signals(request: Request) -> list[Signal]:
    store: SignalStore = request.app.state.store
    return await store.latest_signals()


@router.post("/refresh")
async def force_refresh(request: Request) -> dict[str, int]:
    app_state = request.app.state
    return await run_refresh(
        store=app_state.store,
        observers=app_state.observers,
        bus=app_state.bus,
    )
```

- [ ] **Step 2: Delete `routers/standup.py`**

```bash
git rm services/api/src/irma_api/routers/standup.py
```

- [ ] **Step 3: Update `app.py`**

Open `services/api/src/irma_api/app.py` and apply these edits:

1. Drop `from irma_api.routers.standup import router as standup_router`.
2. Add `from irma_api.routers.projects import router as projects_router`.
3. Add `from irma_api.routers.tasks import router as tasks_router`.
4. Add `from irma_api.routers.brief import router as brief_router`.
5. Remove the `lead_agent.synthesize(signals)` block from the `tick` closure — `tick = lambda: run_refresh(store=store, observers=observers, bus=bus)` (no `lead_agent` arg).
6. Update the `LeadAgent(...)` constructor call site in `lifespan()` to the new signature (`settings=, llm=, store=`). The new signature is unchanged because LeadAgent still takes `store=` and pulls projects/tasks/cache from it via its own ProjectRepo/TaskRepo/BriefCacheRepo. (This is the contract Task 4.2 enforces.)
7. In `create_app()` router registration:
   - delete `app.include_router(standup_router, prefix="/api/v1")`
   - add `app.include_router(projects_router, prefix="/api/v1")`
   - add `app.include_router(tasks_router, prefix="/api/v1")`
   - add `app.include_router(brief_router, prefix="/api/v1")`

After edits, the `lifespan` should resemble:

```python
async def tick() -> None:
    await run_refresh(store=store, observers=observers, bus=bus)
```

- [ ] **Step 4: Type-check + run the suite**

```bash
cd services/api && uv run ruff check . && uv run mypy --strict src/irma_api && uv run pytest -q
```

Expected: ruff/mypy clean, all router + repo + model + migration tests green. The dead `test_brief_parse.py` was removed in Task 1.3; if any new red appears, it should be in `lead_agent.py` (still old shape — fixed in Task 4.2). Skip-mark or comment out that test file if it blocks: `git mv services/api/tests/test_brief_parse.py /tmp` was already done; double-check no other tests reference `StandupBrief`.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/app.py services/api/src/irma_api/routers/signals.py services/api/src/irma_api/routers/standup.py
git commit -m "$(cat <<'EOF'
feat(api): wire projects/tasks/brief routers; drop /standup

run_refresh no longer eagerly synthesizes — it invalidates brief_cache
instead. Briefs are computed lazily on the next GET. Old standup
router and its eager-synth tick branch are deleted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Synthesis rewrite

Three tasks. The persona prompt becomes a separate file, `LeadAgent` is rewritten as a horizon dispatcher, and the brief router is wired to it.

### Task 4.1: Persona prompt as a loaded file

**Files:**
- Create: `services/api/src/irma_api/agents/prompts/__init__.py`
- Create: `services/api/src/irma_api/agents/prompts/irma_persona.md`

- [ ] **Step 1: Write the persona file**

Create `services/api/src/irma_api/agents/prompts/irma_persona.md`:

```markdown
You are Irma — a calm, anticipatory PMO chief of staff for an AI
researcher. You receive a structured snapshot of the user's projects,
manually-entered tasks, and calendar events, and produce a single
horizon-aware brief in your own voice.

Tone: terse, factual, slightly proactive. No filler. No
"I'll-be-happy-to-help" boilerplate. Surface cross-project conflicts
and deadline pressure as the most useful information you can offer.

You MUST respond with ONLY a single JSON object — no Markdown, no
fences, no commentary before or after — matching exactly this schema:

{
  "horizon":       "<one of: day | week | month | all — match the request>",
  "generated_at":  "<ISO-8601 datetime, UTC>",
  "focus": [
    {
      "kind":         "<task | event>",
      "title":        "<short>",
      "project_id":   "<string or null>",
      "project_name": "<string or null>",
      "task_id":      "<string or null — only when kind=task>",
      "due_date":     "<YYYY-MM-DD or null>",
      "scheduled_for":"<YYYY-MM-DD or null>",
      "when":         "<ISO-8601 string or null — only when kind=event>",
      "note":         "<short or empty>"
    }
  ],
  "project_status": [
    {
      "project_id":     "<string>",
      "project_name":   "<string>",
      "open_tasks":     <integer>,
      "done_tasks":     <integer>,
      "days_to_target": <integer or null>,
      "note":           "<short or empty>"
    }
  ],
  "conflicts":      ["<one cross-project clash>", ...],
  "recommendation": "<single highest-leverage next move, 1-3 sentences>",
  "narrative":      "<your voice, <= 4 sentences>"
}

Rules per horizon:

- day:    focus = today's tasks + today's events, in priority order.
          project_status optional. Conflicts = today-only clashes.
- week:   focus = this-week's tasks + salient events.
          project_status = each active project's weekly trajectory.
          Conflicts = within-week clashes.
- month:  focus optional (large items only).
          project_status = each active project's monthly rollup with
          days_to_target if target_date is set.
          Conflicts = cross-project deadline pressure.
- all:    no time window. project_status = all active projects.
          focus = empty unless something is critically overdue.
          Conflicts = strategic, persistent.

If a section has no real content for the requested horizon, return an
empty list — do not invent. Speak as Irma; reference the user as
"you".
```

- [ ] **Step 2: Implement the loader**

Create `services/api/src/irma_api/agents/prompts/__init__.py`:

```python
"""Prompt loader. Reads the markdown files shipped next to this module."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    """Return the contents of `<name>.md`. Raises FileNotFoundError if missing."""
    path = _DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
```

- [ ] **Step 3: Commit**

```bash
git add services/api/src/irma_api/agents/prompts/
git commit -m "$(cat <<'EOF'
feat(api): Irma persona prompt as a loaded markdown file

agents/prompts/irma_persona.md holds the system prompt; load_prompt()
caches it. Lets us edit voice and per-horizon rules without touching code.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.2: Rewrite `LeadAgent` as a horizon dispatcher

**Files:**
- Modify (rewrite): `services/api/src/irma_api/agents/lead_agent.py`
- Create: `services/api/tests/test_lead_agent_horizons.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_lead_agent_horizons.py`:

```python
"""LeadAgent: horizon dispatch, context window, cache hit/miss, retry."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import pytest_asyncio

from irma_api.agents.lead_agent import LeadAgent
from irma_api.agents.llm import ChatTurn, LLMClient
from irma_api.config import Settings
from irma_api.models.brief import Brief, Horizon
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
        self, *, system: str, messages: Sequence[ChatTurn], max_tokens: int
    ) -> str:
        self.calls.append((system, list(messages)))
        return self._responses.pop(0)


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
    await trepo.create(
        TaskCreate(project_id=p.id, title="today", scheduled_for=date(2026, 5, 27))
    )
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
    assert llm.calls and llm.calls[0][0]  # system prompt non-empty
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
    llm = FakeLLM([])  # would raise on pop if called
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
async def test_all_four_horizons_dispatch(
    seeded_store: SignalStore, horizon: Horizon
) -> None:
    llm = FakeLLM([_brief_json(horizon)])
    agent = LeadAgent(settings=_settings(), llm=llm, store=seeded_store)
    b = await agent.synthesize(horizon)
    assert b.horizon == horizon
    await seeded_store.close()
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd services/api && uv run pytest tests/test_lead_agent_horizons.py -v
```

Expected: import errors / failures — the new LeadAgent doesn't exist yet.

- [ ] **Step 3: Rewrite `agents/lead_agent.py`**

Overwrite `services/api/src/irma_api/agents/lead_agent.py`:

```python
"""LeadAgent — horizon-aware PMO synthesis.

Given a Horizon, builds a per-window SynthesisContext, composes a prompt
against the Irma persona, calls LLMClient.complete(), parses the response
to a Brief, caches it keyed on (horizon, inputs_hash), and returns. One
JSON-parse retry; second failure raises BriefSynthesisError.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final

import structlog
from pydantic import ValidationError

from irma_api.agents.llm import ChatTurn, LLMClient
from irma_api.agents.prompts import load_prompt
from irma_api.config import Settings
from irma_api.models.brief import Brief, Horizon
from irma_api.models.project import Project, ProjectStatus
from irma_api.models.signal import Signal
from irma_api.models.task import Task, TaskStatus
from irma_api.store.repos.brief_cache_repo import BriefCacheRepo
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore

logger = structlog.get_logger(__name__)


class BriefSynthesisError(RuntimeError):
    """LLM failed to produce a valid Brief after one retry."""


_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^```[a-zA-Z]*\s*|\s*```\s*$")


def _strip_fences(text: str) -> str:
    stripped = _FENCE_RE.sub("", text.strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        return stripped
    return stripped[start : end + 1]


def _parse_brief(text: str) -> Brief:
    cleaned = _strip_fences(text)
    try:
        return Brief.model_validate_json(cleaned)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("lead_agent.parse_failed", error=str(exc)[:200], head=cleaned[:200])
        raise BriefSynthesisError(str(exc)) from exc


@dataclass(frozen=True)
class SynthesisContext:
    horizon: Horizon
    today: date
    window_start: date
    window_end: date | None  # None for `all`
    projects: list[Project]
    tasks: list[Task]
    signals: list[Signal]


def _window_for(horizon: Horizon, today: date) -> tuple[date, date | None]:
    if horizon == "day":
        return today, today
    if horizon == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    if horizon == "month":
        start = today.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
        return start, end
    return today, None  # "all"


def _inputs_hash(ctx: SynthesisContext) -> str:
    """Stable hash over the inputs that materially shape the brief."""
    parts: list[str] = [ctx.horizon, ctx.today.isoformat()]
    for p in sorted(ctx.projects, key=lambda x: x.id):
        parts.append(f"p:{p.id}:{p.updated_at.isoformat()}")
    for t in sorted(ctx.tasks, key=lambda x: x.id):
        parts.append(f"t:{t.id}:{t.updated_at.isoformat()}")
    for s in sorted(ctx.signals, key=lambda x: x.hash_key()):
        parts.append(f"s:{s.hash_key()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


class LeadAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        store: SignalStore,
        max_tokens: int = 1500,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._store = store
        self._max_tokens = max_tokens

    # --- public ---------------------------------------------------------------

    async def synthesize(self, horizon: Horizon) -> Brief:
        ctx = await self._build_context(horizon)
        cache = BriefCacheRepo(self._store.connection)
        inputs_hash = _inputs_hash(ctx)
        cached = await cache.get(horizon, inputs_hash=inputs_hash)
        if cached is not None:
            logger.info("lead_agent.cache_hit", horizon=horizon)
            return cached

        if not ctx.projects and not ctx.tasks and not ctx.signals:
            brief = self._empty_brief(horizon)
            await cache.put(horizon, inputs_hash=inputs_hash, brief=brief)
            return brief

        brief = await self._call_and_parse(ctx)
        await cache.put(horizon, inputs_hash=inputs_hash, brief=brief)
        logger.info(
            "lead_agent.brief_ready", horizon=horizon, conflicts=len(brief.conflicts)
        )
        return brief

    # --- private --------------------------------------------------------------

    async def _build_context(self, horizon: Horizon) -> SynthesisContext:
        today = datetime.now(UTC).date()
        start, end = _window_for(horizon, today)

        prepo = ProjectRepo(self._store.connection)
        trepo = TaskRepo(self._store.connection)
        projects = await prepo.list(statuses=[ProjectStatus.ACTIVE])

        open_statuses = [TaskStatus.TODO, TaskStatus.DOING, TaskStatus.BLOCKED]
        if horizon == "all":
            tasks = await trepo.list(statuses=open_statuses)
        else:
            # Union: scheduled-in-window OR due-before-end-of-window.
            scheduled = await trepo.list(
                statuses=open_statuses,
                scheduled_from=start,
                scheduled_to=end,
            )
            due_soon = await trepo.list(statuses=open_statuses, due_before=end)
            by_id = {t.id: t for t in scheduled}
            for t in due_soon:
                by_id.setdefault(t.id, t)
            tasks = list(by_id.values())

        # Recent calendar signals — small bounded window keyed on horizon.
        sig_limit = {"day": 50, "week": 200, "month": 500, "all": 0}[horizon]
        signals: list[Signal] = (
            [] if sig_limit == 0 else await self._store.latest_signals(limit=sig_limit)
        )
        return SynthesisContext(
            horizon=horizon,
            today=today,
            window_start=start,
            window_end=end,
            projects=projects,
            tasks=tasks,
            signals=signals,
        )

    async def _call_and_parse(self, ctx: SynthesisContext) -> Brief:
        system = load_prompt("irma_persona")
        user = self._compose_user_message(ctx)
        messages: list[ChatTurn] = [ChatTurn(role="user", content=user)]

        text = await self._llm.complete(
            system=system, messages=messages, max_tokens=self._max_tokens
        )
        try:
            return _parse_brief(text)
        except BriefSynthesisError:
            messages.append(ChatTurn(role="assistant", content=text))
            messages.append(
                ChatTurn(
                    role="user",
                    content=(
                        "Your previous reply did not parse as the required JSON "
                        "object. Reply with ONLY the JSON object now."
                    ),
                )
            )
            retry = await self._llm.complete(
                system=system, messages=messages, max_tokens=self._max_tokens
            )
            return _parse_brief(retry)

    def _compose_user_message(self, ctx: SynthesisContext) -> str:
        lines: list[str] = [
            f"HORIZON: {ctx.horizon}",
            f"TODAY: {ctx.today.isoformat()}",
        ]
        if ctx.window_end:
            lines.append(f"WINDOW: {ctx.window_start} → {ctx.window_end}")
        else:
            lines.append("WINDOW: all time")

        lines.append("")
        lines.append("ACTIVE PROJECTS:")
        for p in ctx.projects:
            target = (
                f"target {p.target_date.isoformat()}" if p.target_date else "no target"
            )
            lines.append(f"  • [{p.id}] {p.name}  priority={p.priority}  {target}")
            for g in p.goals:
                lines.append(f"      goal: {g}")

        lines.append("")
        lines.append("TASKS IN WINDOW:")
        if ctx.tasks:
            for t in ctx.tasks:
                bits = [f"status={t.status.value}"]
                if t.due_date:
                    bits.append(f"due={t.due_date.isoformat()}")
                if t.scheduled_for:
                    bits.append(f"sched={t.scheduled_for.isoformat()}")
                if t.estimated_minutes:
                    bits.append(f"est={t.estimated_minutes}m")
                lines.append(
                    f"  • [{t.id}] (project {t.project_id})  {t.title}  "
                    f"[{', '.join(bits)}]"
                )
        else:
            lines.append("  (none)")

        lines.append("")
        lines.append("CALENDAR SIGNALS IN WINDOW:")
        if ctx.signals:
            for s in ctx.signals:
                lines.append(
                    f"  • {s.ts.isoformat()}  {s.title}"
                    + (f" — {s.detail}" if s.detail else "")
                )
        else:
            lines.append("  (none)")

        now_iso = datetime.now(UTC).isoformat()
        lines.append("")
        lines.append(
            f"Produce the Brief JSON now. Use generated_at = {now_iso} and "
            f'horizon = "{ctx.horizon}".'
        )
        return "\n".join(lines)

    def _empty_brief(self, horizon: Horizon) -> Brief:
        return Brief(
            horizon=horizon,
            generated_at=datetime.now(UTC),
            focus=[],
            project_status=[],
            conflicts=[],
            recommendation="Add a project to get started.",
            narrative="",
        )
```

- [ ] **Step 4: Run the test**

```bash
cd services/api && uv run pytest tests/test_lead_agent_horizons.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run the whole suite + ruff + mypy**

```bash
cd services/api && uv run ruff check . && uv run mypy --strict src/irma_api && uv run pytest -q
```

Expected: green.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/agents/lead_agent.py services/api/tests/test_lead_agent_horizons.py
git commit -m "$(cat <<'EOF'
feat(api): rewrite LeadAgent as horizon-aware synthesizer

synthesize(horizon) builds a per-window SynthesisContext (projects +
tasks + bounded calendar signals), composes the persona-driven prompt,
calls LLMClient.complete, caches the parsed Brief keyed on
(horizon, inputs_hash). Empty context short-circuits without calling
the LLM. One JSON-parse retry; second failure raises BriefSynthesisError.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.3: Smoke-test the live brief router

**Files:**
- Modify: `services/api/tests/test_routers_brief.py` (add an integration test)

- [ ] **Step 1: Append an integration test**

Add to the end of `services/api/tests/test_routers_brief.py`:

```python
import pytest_asyncio
from irma_api.agents.lead_agent import LeadAgent
from irma_api.agents.llm import ChatTurn
from irma_api.config import Settings
from irma_api.routers.projects import router as projects_router


class _FakeLLM:
    backend = "fake"
    model = "fake-1"

    async def complete(self, *, system, messages, max_tokens):
        return (
            '{"horizon":"day","generated_at":"2026-05-27T12:00:00+00:00",'
            '"focus":[],"project_status":[],"conflicts":[],'
            '"recommendation":"ok","narrative":""}'
        )


@pytest_asyncio.fixture
async def live_client(tmp_path):
    from collections.abc import AsyncIterator
    app = FastAPI()
    store = SignalStore(tmp_path / "irma.db")
    await store.connect()
    settings = Settings(
        irma_db_path=tmp_path / "irma.db",
        anthropic_api_key=None,
        anthropic_model="x",
    )
    app.state.store = store
    app.state.lead_agent = LeadAgent(settings=settings, llm=_FakeLLM(), store=store)
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(brief_router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await store.close()


@pytest.mark.asyncio
async def test_brief_today_with_project_returns_200(live_client) -> None:
    r = await live_client.post("/api/v1/projects", json={"name": "Thesis"})
    assert r.status_code == 201
    r2 = await live_client.get("/api/v1/brief/today")
    assert r2.status_code == 200
    assert r2.json()["horizon"] == "day"
```

- [ ] **Step 2: Run**

```bash
cd services/api && uv run pytest tests/test_routers_brief.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add services/api/tests/test_routers_brief.py
git commit -m "$(cat <<'EOF'
test(api): integration test wiring LeadAgent into the brief router

Verifies /api/v1/brief/today returns 200 with a parsed Brief when
LeadAgent is configured with a fake LLM.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Observer + scheduler changes

Three small tasks. Adds the CodebaseAgent kill-switch, drops the eager-synth tick, and annotates the agent docstring.

### Task 5.1: `irma_codebase_agent_enabled` setting + `.env.example`

**Files:**
- Modify: `services/api/src/irma_api/config.py`
- Modify: `services/api/.env.example`

- [ ] **Step 1: Add the setting**

In `services/api/src/irma_api/config.py`, add (under the `# --- Observers ---` block):

```python
    irma_codebase_agent_enabled: bool = False
```

- [ ] **Step 2: Update `.env.example`**

Append to `services/api/.env.example`:

```
# Observers
# Local CodebaseAgent is disabled by default — most code lives on SSH
# servers; the local-only variant misses it. Set to true to re-enable
# the local git observer.
IRMA_CODEBASE_AGENT_ENABLED=false
```

- [ ] **Step 3: Commit**

```bash
git add services/api/src/irma_api/config.py services/api/.env.example
git commit -m "$(cat <<'EOF'
feat(api): IRMA_CODEBASE_AGENT_ENABLED kill-switch (default off)

The local CodebaseAgent is gated; SSH-aware variant is a future spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.2: Gate `CodebaseAgent` registration in `app.py`

**Files:**
- Modify: `services/api/src/irma_api/app.py`

- [ ] **Step 1: Edit `lifespan()`**

Replace the observer-construction block in `services/api/src/irma_api/app.py` with:

```python
    observers: list[Observer] = [TimeAgent(settings)]
    if settings.irma_codebase_agent_enabled:
        observers.append(CodebaseAgent(settings.irma_repos))
```

- [ ] **Step 2: Verify**

```bash
cd services/api && uv run ruff check . && uv run mypy --strict src/irma_api && uv run pytest -q
```

Expected: green.

- [ ] **Step 3: Commit**

```bash
git add services/api/src/irma_api/app.py
git commit -m "$(cat <<'EOF'
feat(api): gate CodebaseAgent on IRMA_CODEBASE_AGENT_ENABLED

When the flag is false (default), only TimeAgent runs. Keeps
CodebaseAgent code intact for a future SSH-aware variant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.3: Annotate `codebase_agent.py` docstring

**Files:**
- Modify: `services/api/src/irma_api/agents/codebase_agent.py`

- [ ] **Step 1: Update the module docstring**

Open `services/api/src/irma_api/agents/codebase_agent.py` and replace the top-of-file docstring with:

```python
"""CodebaseAgent — local git observer.

Disabled by default (see config.irma_codebase_agent_enabled). The
local-only design misses the user's primary codebase, which lives on
SSH servers. A future spec will introduce an SSH-aware variant; until
then this module is retained but not registered.
"""
```

- [ ] **Step 2: Commit**

```bash
git add services/api/src/irma_api/agents/codebase_agent.py
git commit -m "$(cat <<'EOF'
docs(api): annotate CodebaseAgent as disabled pending SSH variant

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — Frontend

Six tasks. No unit tests (per spec §9 — minimal dashboard, no business logic worth covering). Each task ends with a manual verification step in the Vite dev server.

**Dev server commands** (run in two terminals from the repo root):

```bash
# terminal 1 — backend
cd services/api && uv run uvicorn irma_api.main:app --factory --reload --port 8765
# terminal 2 — desktop frontend (browser-mode for dev iteration)
cd apps/desktop && npm run dev
```

The dashboard is reachable at `http://localhost:1420/main.html` (or whichever path Vite reports for the main entry).

### Task 6.1: Types — add `Project`, `Task`, `Brief`; drop `StandupBrief`

**Files:**
- Modify (rewrite): `apps/desktop/src/lib/types.ts`

- [ ] **Step 1: Rewrite the types module**

Overwrite `apps/desktop/src/lib/types.ts`:

```ts
export type AgentState = "idle" | "observing" | "thinking" | "alert";

export interface SpriteFrameSpec {
  frames: number[];
  fps: number;
  loop: boolean;
}

export interface SpriteManifest {
  frameWidth: number;
  frameHeight: number;
  columns: number;
  rows?: number;
  scale?: number;
  states: Record<AgentState, SpriteFrameSpec>;
  extras?: Record<string, SpriteFrameSpec>;
}

export interface Signal {
  source: "calendar" | "codebase";
  kind: string;
  title: string;
  detail: string;
  ts: string;
  meta: Record<string, unknown>;
}

export type ChatRole = "user" | "assistant";
export interface ChatMessage { role: ChatRole; content: string; }
export interface ChatResponse { reply: string; backend: string; model: string; }

// --- Projects + Tasks ----------------------------------------------------

export type ProjectStatus = "active" | "paused" | "archived";

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  priority: 1 | 2 | 3;
  calendar_keywords: string[];
  goals: string[];
  target_date: string | null; // YYYY-MM-DD
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  status?: ProjectStatus;
  priority?: 1 | 2 | 3;
  calendar_keywords?: string[];
  goals?: string[];
  target_date?: string | null;
}

export type ProjectUpdate = Partial<ProjectCreate>;

export type TaskStatus = "todo" | "doing" | "done" | "blocked";

export interface Task {
  id: string;
  project_id: string;
  title: string;
  notes: string;
  status: TaskStatus;
  due_date: string | null;
  scheduled_for: string | null;
  estimated_minutes: number | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskCreate {
  project_id: string;
  title: string;
  notes?: string;
  status?: TaskStatus;
  due_date?: string | null;
  scheduled_for?: string | null;
  estimated_minutes?: number | null;
}

export type TaskUpdate = Partial<Omit<TaskCreate, "project_id">>;

// --- Brief ---------------------------------------------------------------

export type Horizon = "day" | "week" | "month" | "all";

export type FocusKind = "task" | "event";

export interface FocusItem {
  kind: FocusKind;
  title: string;
  project_id: string | null;
  project_name: string | null;
  task_id: string | null;
  due_date: string | null;
  scheduled_for: string | null;
  when: string | null;
  note: string;
}

export interface ProjectStatusItem {
  project_id: string;
  project_name: string;
  open_tasks: number;
  done_tasks: number;
  days_to_target: number | null;
  note: string;
}

export interface Brief {
  horizon: Horizon;
  generated_at: string;
  focus: FocusItem[];
  project_status: ProjectStatusItem[];
  conflicts: string[];
  recommendation: string;
  narrative: string;
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd apps/desktop && npx tsc --noEmit
```

Expected: errors in files that still import `StandupBrief` (`api.ts`, `App.tsx`, `StandupView.tsx`). They land in subsequent tasks.

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src/lib/types.ts
git commit -m "$(cat <<'EOF'
feat(desktop): replace StandupBrief types with Project/Task/Brief shape

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.2: API client — endpoints for projects, tasks, brief

**Files:**
- Modify (rewrite): `apps/desktop/src/lib/api.ts`

- [ ] **Step 1: Rewrite `api.ts`**

Overwrite `apps/desktop/src/lib/api.ts`:

```ts
import type {
  Brief,
  ChatMessage,
  ChatResponse,
  Horizon,
  Project,
  ProjectCreate,
  ProjectStatus,
  ProjectUpdate,
  Signal,
  Task,
  TaskCreate,
  TaskStatus,
  TaskUpdate,
} from "./types";

const BASE_URL: string =
  (import.meta.env.VITE_IRMA_API as string | undefined) ??
  "http://127.0.0.1:8765";

export const IRMA_API_BASE = BASE_URL;

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${detail}`);
  }
  return (await res.json()) as T;
}

async function noContent(res: Response): Promise<void> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${detail}`);
  }
}

function url(path: string, params?: Record<string, string | string[] | undefined>): string {
  const u = new URL(`${BASE_URL}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined) continue;
      if (Array.isArray(v)) v.forEach((vi) => u.searchParams.append(k, vi));
      else u.searchParams.append(k, v);
    }
  }
  return u.toString();
}

// --- Projects -------------------------------------------------------------

export async function listProjects(statuses?: ProjectStatus[]): Promise<Project[]> {
  return jsonOrThrow(await fetch(url("/api/v1/projects", { status: statuses })));
}

export async function createProject(p: ProjectCreate): Promise<Project> {
  return jsonOrThrow(
    await fetch(url("/api/v1/projects"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }),
  );
}

export async function getProject(id: string): Promise<Project> {
  return jsonOrThrow(await fetch(url(`/api/v1/projects/${id}`)));
}

export async function updateProject(id: string, patch: ProjectUpdate): Promise<Project> {
  return jsonOrThrow(
    await fetch(url(`/api/v1/projects/${id}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteProject(id: string): Promise<void> {
  await noContent(await fetch(url(`/api/v1/projects/${id}`), { method: "DELETE" }));
}

// --- Tasks ----------------------------------------------------------------

export async function listTasks(opts: {
  project_id?: string;
  status?: TaskStatus[];
  scheduled_from?: string;
  scheduled_to?: string;
  due_before?: string;
} = {}): Promise<Task[]> {
  return jsonOrThrow(
    await fetch(
      url("/api/v1/tasks", {
        project_id: opts.project_id,
        status: opts.status,
        scheduled_from: opts.scheduled_from,
        scheduled_to: opts.scheduled_to,
        due_before: opts.due_before,
      }),
    ),
  );
}

export async function createTask(t: TaskCreate): Promise<Task> {
  return jsonOrThrow(
    await fetch(url("/api/v1/tasks"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(t),
    }),
  );
}

export async function updateTask(id: string, patch: TaskUpdate): Promise<Task> {
  return jsonOrThrow(
    await fetch(url(`/api/v1/tasks/${id}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteTask(id: string): Promise<void> {
  await noContent(await fetch(url(`/api/v1/tasks/${id}`), { method: "DELETE" }));
}

export async function completeTask(id: string): Promise<Task> {
  return jsonOrThrow(
    await fetch(url(`/api/v1/tasks/${id}/complete`), { method: "POST" }),
  );
}

// --- Brief ----------------------------------------------------------------

export async function fetchBrief(horizon: Horizon): Promise<Brief> {
  const path = ({
    day: "today",
    week: "week",
    month: "month",
    all: "overview",
  } as const)[horizon];
  return jsonOrThrow(await fetch(url(`/api/v1/brief/${path}`)));
}

// --- Signals / refresh / chat (existing, kept) ----------------------------

export async function fetchSignals(): Promise<Signal[]> {
  return jsonOrThrow(await fetch(url("/api/v1/signals")));
}

export async function forceRefresh(): Promise<void> {
  await noContent(await fetch(url("/api/v1/refresh"), { method: "POST" }));
}

export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
  return jsonOrThrow(
    await fetch(url("/api/v1/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    }),
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd apps/desktop && npx tsc --noEmit
```

Expected: remaining errors only in `App.tsx`, `StandupView.tsx`, `mockBrief.ts` (handled next).

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src/lib/api.ts
git commit -m "$(cat <<'EOF'
feat(desktop): typed API client for projects/tasks/brief

Drops fetchStandup; adds list/create/get/update/delete for projects
and tasks, plus completeTask shortcut and horizon-aware fetchBrief.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.3: Brief view components

**Files:**
- Create: `apps/desktop/src/main/brief/BriefView.tsx`
- Create: `apps/desktop/src/main/brief/HorizonTabs.tsx`
- Create: `apps/desktop/src/main/brief/FocusList.tsx`
- Create: `apps/desktop/src/main/brief/ConflictList.tsx`
- Create: `apps/desktop/src/main/brief/Narrative.tsx`

- [ ] **Step 1: Create `HorizonTabs.tsx`**

```tsx
import type { Horizon } from "../../lib/types";

const ORDER: { id: Horizon; label: string }[] = [
  { id: "day", label: "Today" },
  { id: "week", label: "Week" },
  { id: "month", label: "Month" },
  { id: "all", label: "Overview" },
];

export function HorizonTabs({
  current,
  onChange,
}: {
  current: Horizon;
  onChange: (h: Horizon) => void;
}) {
  return (
    <div className="flex gap-1 text-sm">
      {ORDER.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          type="button"
          className={
            "px-3 py-1 rounded border transition-colors " +
            (current === t.id
              ? "border-irma-indigo text-irma-text bg-irma-surface"
              : "border-transparent text-irma-mute hover:text-irma-text")
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create `FocusList.tsx`**

```tsx
import type { FocusItem } from "../../lib/types";

export function FocusList({
  items,
  onCompleteTask,
}: {
  items: FocusItem[];
  onCompleteTask: (taskId: string) => void | Promise<void>;
}) {
  if (items.length === 0) return null;
  return (
    <section>
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">Focus</h3>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={`${it.kind}-${it.task_id ?? i}`} className="flex items-start gap-3">
            {it.kind === "task" && it.task_id ? (
              <input
                type="checkbox"
                onChange={() => void onCompleteTask(it.task_id!)}
                className="mt-1 accent-irma-indigo"
                aria-label={`Complete ${it.title}`}
              />
            ) : (
              <span className="mt-1">📅</span>
            )}
            <div className="flex-1 min-w-0">
              <div className="text-sm">{it.title}</div>
              <div className="text-xs text-irma-mute">
                {it.project_name ?? "—"}
                {it.due_date ? ` · due ${it.due_date}` : ""}
                {it.scheduled_for ? ` · sched ${it.scheduled_for}` : ""}
                {it.when ? ` · ${it.when}` : ""}
                {it.note ? ` · ${it.note}` : ""}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 3: Create `ConflictList.tsx`**

```tsx
export function ConflictList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section className="border border-irma-amber/40 rounded-lg p-4 bg-irma-amber/5">
      <h3 className="text-xs uppercase tracking-widest text-irma-amber mb-2">
        Conflicts
      </h3>
      <ul className="text-sm space-y-1 list-disc list-inside">
        {items.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Create `Narrative.tsx`**

```tsx
export function Narrative({ text }: { text: string }) {
  if (!text) return null;
  return (
    <section>
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">
        Narrative
      </h3>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{text}</p>
    </section>
  );
}
```

- [ ] **Step 5: Create `BriefView.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { completeTask, fetchBrief } from "../../lib/api";
import type { Brief, Horizon } from "../../lib/types";
import { ConflictList } from "./ConflictList";
import { FocusList } from "./FocusList";
import { HorizonTabs } from "./HorizonTabs";
import { Narrative } from "./Narrative";

export function BriefView({ agentSignal }: { agentSignal: number }) {
  const [horizon, setHorizon] = useState<Horizon>("day");
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (h: Horizon) => {
    setLoading(true);
    setError(null);
    try {
      setBrief(await fetchBrief(h));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Reload whenever horizon changes OR the parent signals a backend settle.
  useEffect(() => {
    void load(horizon);
  }, [horizon, agentSignal, load]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <HorizonTabs current={horizon} onChange={setHorizon} />
        {loading && <span className="text-xs text-irma-mute">loading…</span>}
      </div>

      {error && (
        <div className="text-sm text-irma-amber">Brief unavailable: {error}</div>
      )}

      {brief && (
        <>
          {brief.recommendation && (
            <section className="border border-irma-border rounded-lg p-4 bg-irma-surface">
              <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">
                Recommendation
              </h3>
              <p className="text-sm leading-relaxed">{brief.recommendation}</p>
            </section>
          )}
          <FocusList
            items={brief.focus}
            onCompleteTask={async (tid) => {
              await completeTask(tid);
              await load(horizon);
            }}
          />
          <ConflictList items={brief.conflicts} />
          {brief.project_status.length > 0 && (
            <section>
              <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">
                Project status
              </h3>
              <ul className="space-y-2 text-sm">
                {brief.project_status.map((ps) => (
                  <li key={ps.project_id} className="border border-irma-border rounded p-3">
                    <div className="font-medium">{ps.project_name}</div>
                    <div className="text-xs text-irma-mute">
                      open {ps.open_tasks} · done {ps.done_tasks}
                      {ps.days_to_target !== null ? ` · ${ps.days_to_target}d to target` : ""}
                    </div>
                    {ps.note && <div className="text-xs mt-1">{ps.note}</div>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <Narrative text={brief.narrative} />
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/src/main/brief/
git commit -m "$(cat <<'EOF'
feat(desktop): BriefView with horizon tabs and brief sections

HorizonTabs + FocusList + ConflictList + Narrative + project_status
block. Empty sections collapse. Checkbox on a task focus item calls
completeTask and reloads the active horizon.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.4: Projects view components

**Files:**
- Create: `apps/desktop/src/main/projects/ProjectsView.tsx`
- Create: `apps/desktop/src/main/projects/ProjectList.tsx`
- Create: `apps/desktop/src/main/projects/ProjectDetail.tsx`
- Create: `apps/desktop/src/main/projects/ProjectForm.tsx`
- Create: `apps/desktop/src/main/projects/TaskList.tsx`
- Create: `apps/desktop/src/main/projects/TaskRow.tsx`
- Create: `apps/desktop/src/main/projects/TaskAddRow.tsx`

- [ ] **Step 1: Create `TaskAddRow.tsx`**

```tsx
import { useState } from "react";
import { createTask } from "../../lib/api";
import type { Task } from "../../lib/types";

export function TaskAddRow({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (t: Task) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [sched, setSched] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-irma-indigo hover:underline"
      >
        + add task
      </button>
    );
  }

  const reset = () => {
    setTitle(""); setDue(""); setSched(""); setOpen(false);
  };

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const t = await createTask({
        project_id: projectId,
        title: title.trim(),
        due_date: due || null,
        scheduled_for: sched || null,
      });
      onCreated(t);
      reset();
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); void submit(); }}
      className="flex flex-wrap gap-2 items-center text-sm py-1.5"
    >
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Task title"
        className="flex-1 min-w-[12rem] bg-irma-bg border border-irma-border rounded px-2 py-1"
      />
      <label className="text-xs text-irma-mute">due
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
               className="ml-1 bg-irma-bg border border-irma-border rounded px-1" />
      </label>
      <label className="text-xs text-irma-mute">sched
        <input type="date" value={sched} onChange={(e) => setSched(e.target.value)}
               className="ml-1 bg-irma-bg border border-irma-border rounded px-1" />
      </label>
      <button type="submit" disabled={busy || !title.trim()}
              className="px-2 py-1 rounded border border-irma-indigo text-irma-indigo">
        save
      </button>
      <button type="button" onClick={reset}
              className="px-2 py-1 rounded text-irma-mute">
        cancel
      </button>
    </form>
  );
}
```

- [ ] **Step 2: Create `TaskRow.tsx`**

```tsx
import { useState } from "react";
import { completeTask, deleteTask, updateTask } from "../../lib/api";
import type { Task, TaskStatus } from "../../lib/types";

const STATUSES: TaskStatus[] = ["todo", "doing", "done", "blocked"];

export function TaskRow({
  task,
  onChanged,
  onDeleted,
}: {
  task: Task;
  onChanged: (t: Task) => void;
  onDeleted: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState(task.notes);
  const [status, setStatus] = useState<TaskStatus>(task.status);
  const [due, setDue] = useState(task.due_date ?? "");
  const [sched, setSched] = useState(task.scheduled_for ?? "");
  const [estimate, setEstimate] = useState(
    task.estimated_minutes !== null ? String(task.estimated_minutes) : "",
  );

  const save = async () => {
    const patch = {
      notes,
      status,
      due_date: due || null,
      scheduled_for: sched || null,
      estimated_minutes: estimate ? Number(estimate) : null,
    };
    const updated = await updateTask(task.id, patch);
    onChanged(updated);
  };

  return (
    <li className="border-b border-irma-border last:border-b-0 py-2">
      <div className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={task.status === "done"}
          onChange={async () => {
            const next =
              task.status === "done"
                ? await updateTask(task.id, { status: "todo" })
                : await completeTask(task.id);
            onChanged(next);
          }}
          className="accent-irma-indigo"
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={
            "flex-1 text-left " + (task.status === "done" ? "line-through text-irma-mute" : "")
          }
        >
          {task.title}
        </button>
        <span className="text-xs text-irma-mute">
          {task.due_date ? `due ${task.due_date}` : ""}
          {task.scheduled_for ? ` · sched ${task.scheduled_for}` : ""}
        </span>
      </div>

      {open && (
        <div className="mt-2 pl-6 grid grid-cols-2 gap-2 text-xs text-irma-mute">
          <label className="col-span-2">notes
            <textarea
              value={notes} onChange={(e) => setNotes(e.target.value)}
              onBlur={() => void save()}
              className="w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text"
            />
          </label>
          <label>status
            <select value={status} onChange={(e) => { setStatus(e.target.value as TaskStatus); void save(); }}
                    className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>est min
            <input type="number" min={1} value={estimate}
                   onChange={(e) => setEstimate(e.target.value)} onBlur={() => void save()}
                   className="ml-1 w-16 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
          <label>due
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} onBlur={() => void save()}
                   className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
          <label>sched
            <input type="date" value={sched} onChange={(e) => setSched(e.target.value)} onBlur={() => void save()}
                   className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
          <button type="button"
                  onClick={async () => { await deleteTask(task.id); onDeleted(task.id); }}
                  className="col-span-2 text-irma-amber hover:underline text-left">
            delete task
          </button>
        </div>
      )}
    </li>
  );
}
```

- [ ] **Step 3: Create `TaskList.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { listTasks } from "../../lib/api";
import type { Task } from "../../lib/types";
import { TaskAddRow } from "./TaskAddRow";
import { TaskRow } from "./TaskRow";

export function TaskList({ projectId }: { projectId: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTasks(await listTasks({ project_id: projectId }));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <section className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs uppercase tracking-widest text-irma-mute">Tasks</h3>
        <TaskAddRow projectId={projectId} onCreated={(t) => setTasks((ts) => [...ts, t])} />
      </div>
      {loading && tasks.length === 0 && (
        <div className="text-xs text-irma-mute">loading…</div>
      )}
      <ul>
        {tasks.map((t) => (
          <TaskRow
            key={t.id}
            task={t}
            onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
            onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))}
          />
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 4: Create `ProjectForm.tsx`**

```tsx
import { useState } from "react";
import { createProject, updateProject } from "../../lib/api";
import type { Project, ProjectCreate, ProjectStatus } from "../../lib/types";

const STATUSES: ProjectStatus[] = ["active", "paused", "archived"];

export function ProjectForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Project | null;
  onClose: () => void;
  onSaved: (p: Project) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [priority, setPriority] = useState<1 | 2 | 3>(initial?.priority ?? 2);
  const [keywords, setKeywords] = useState(initial?.calendar_keywords.join(", ") ?? "");
  const [goals, setGoals] = useState(initial?.goals.join("\n") ?? "");
  const [target, setTarget] = useState(initial?.target_date ?? "");
  const [status, setStatus] = useState<ProjectStatus>(initial?.status ?? "active");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const payload: ProjectCreate = {
        name: name.trim(),
        description,
        priority,
        status,
        calendar_keywords: keywords
          .split(",").map((s) => s.trim()).filter(Boolean),
        goals: goals.split("\n").map((s) => s.trim()).filter(Boolean),
        target_date: target || null,
      };
      const saved = initial
        ? await updateProject(initial.id, payload)
        : await createProject(payload);
      onSaved(saved);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-10">
      <form onSubmit={submit}
            className="bg-irma-surface border border-irma-border rounded-lg p-5 w-[28rem] space-y-3">
        <h2 className="font-medium">{initial ? "Edit project" : "New project"}</h2>
        <label className="block text-xs text-irma-mute">name
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus
                 className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <label className="block text-xs text-irma-mute">description
          <textarea value={description} onChange={(e) => setDescription(e.target.value)}
                    className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <div className="flex gap-3 text-xs text-irma-mute">
          <label>priority
            <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}
                    className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text">
              <option value={1}>1 high</option>
              <option value={2}>2 med</option>
              <option value={3}>3 low</option>
            </select>
          </label>
          <label>status
            <select value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}
                    className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>target
            <input type="date" value={target} onChange={(e) => setTarget(e.target.value)}
                   className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
        </div>
        <label className="block text-xs text-irma-mute">calendar keywords (comma separated)
          <input value={keywords} onChange={(e) => setKeywords(e.target.value)}
                 className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <label className="block text-xs text-irma-mute">goals (one per line)
          <textarea value={goals} onChange={(e) => setGoals(e.target.value)} rows={3}
                    className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="px-3 py-1 text-irma-mute">cancel</button>
          <button type="submit" disabled={busy || !name.trim()}
                  className="px-3 py-1 border border-irma-indigo text-irma-indigo rounded">
            {initial ? "save" : "create"}
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 5: Create `ProjectDetail.tsx`**

```tsx
import { useState } from "react";
import { deleteProject, updateProject } from "../../lib/api";
import type { Project } from "../../lib/types";
import { ProjectForm } from "./ProjectForm";
import { TaskList } from "./TaskList";

export function ProjectDetail({
  project,
  onChanged,
  onDeleted,
}: {
  project: Project;
  onChanged: (p: Project) => void;
  onDeleted: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);

  const archive = async () => {
    const p = await updateProject(project.id, { status: "archived" });
    onChanged(p);
  };

  const remove = async () => {
    try {
      await deleteProject(project.id);
      onDeleted(project.id);
    } catch (e) {
      alert(`cannot delete: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-medium">{project.name}</h2>
          <div className="text-xs text-irma-mute">
            status {project.status} · priority {project.priority}
            {project.target_date ? ` · target ${project.target_date}` : ""}
          </div>
        </div>
        <div className="flex gap-2 text-xs">
          <button onClick={() => setEditing(true)} className="text-irma-mute hover:text-irma-text">edit</button>
          {project.status !== "archived" && (
            <button onClick={() => void archive()} className="text-irma-mute hover:text-irma-text">archive</button>
          )}
          <button onClick={() => void remove()} className="text-irma-amber">delete</button>
        </div>
      </div>

      {project.description && (
        <p className="text-sm mt-2 whitespace-pre-wrap">{project.description}</p>
      )}

      {project.goals.length > 0 && (
        <section className="mt-3">
          <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-1">Goals</h3>
          <ul className="text-sm list-disc list-inside">
            {project.goals.map((g, i) => <li key={i}>{g}</li>)}
          </ul>
        </section>
      )}

      <TaskList projectId={project.id} />

      {editing && (
        <ProjectForm
          initial={project}
          onClose={() => setEditing(false)}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 6: Create `ProjectList.tsx`**

```tsx
import type { Project } from "../../lib/types";

export function ProjectList({
  projects,
  selectedId,
  onSelect,
  onNew,
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  const active = projects.filter((p) => p.status !== "archived");
  const archived = projects.filter((p) => p.status === "archived");

  return (
    <aside className="w-60 border-r border-irma-border pr-3 text-sm">
      <ul>
        {active.map((p) => (
          <li key={p.id}>
            <button
              type="button"
              onClick={() => onSelect(p.id)}
              className={
                "w-full text-left py-1 px-2 rounded flex items-center gap-2 " +
                (selectedId === p.id
                  ? "bg-irma-surface text-irma-text"
                  : "text-irma-mute hover:text-irma-text")
              }
            >
              <span className="text-xs">P{p.priority}</span>
              <span className="flex-1 truncate">{p.name}</span>
            </button>
          </li>
        ))}
      </ul>
      {archived.length > 0 && (
        <details className="mt-3">
          <summary className="text-xs text-irma-mute cursor-pointer">archived ({archived.length})</summary>
          <ul className="mt-1">
            {archived.map((p) => (
              <li key={p.id}>
                <button onClick={() => onSelect(p.id)}
                        className="w-full text-left py-1 px-2 rounded text-irma-mute hover:text-irma-text">
                  {p.name}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <button onClick={onNew} className="mt-3 w-full text-left text-xs text-irma-indigo px-2 py-1">
        + new project
      </button>
    </aside>
  );
}
```

- [ ] **Step 7: Create `ProjectsView.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";
import { listProjects } from "../../lib/api";
import type { Project } from "../../lib/types";
import { ProjectDetail } from "./ProjectDetail";
import { ProjectForm } from "./ProjectForm";
import { ProjectList } from "./ProjectList";

export function ProjectsView() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const all = await listProjects(["active", "paused", "archived"]);
    setProjects(all);
    if (!selectedId && all.length > 0) setSelectedId(all[0].id);
  }, [selectedId]);

  useEffect(() => { void load(); }, [load]);

  const selected = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="flex gap-4 min-h-[24rem]">
      <ProjectList
        projects={projects}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onNew={() => setCreating(true)}
      />
      <main className="flex-1 min-w-0">
        {selected ? (
          <ProjectDetail
            project={selected}
            onChanged={(p) => setProjects((cur) => cur.map((c) => (c.id === p.id ? p : c)))}
            onDeleted={(id) => {
              setProjects((cur) => cur.filter((c) => c.id !== id));
              setSelectedId(null);
            }}
          />
        ) : (
          <div className="text-sm text-irma-mute">Select a project on the left, or create one.</div>
        )}
      </main>

      {creating && (
        <ProjectForm
          initial={null}
          onClose={() => setCreating(false)}
          onSaved={(p) => { setProjects((cur) => [...cur, p]); setSelectedId(p.id); }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 8: Commit**

```bash
git add apps/desktop/src/main/projects/
git commit -m "$(cat <<'EOF'
feat(desktop): ProjectsView with two-pane list + detail + task CRUD

ProjectList sorts active first (archived collapsed). ProjectDetail shows
header, goals, and TaskList with inline TaskRow/TaskAddRow. ProjectForm
is a modal for create + edit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.5: Rewrite `App.tsx` — header tabs + state-aware reload

**Files:**
- Modify (rewrite): `apps/desktop/src/main/App.tsx`
- Delete: `apps/desktop/src/main/StandupView.tsx`
- Delete: `apps/desktop/src/main/mockBrief.ts`

- [ ] **Step 1: Rewrite `App.tsx`**

Overwrite `apps/desktop/src/main/App.tsx`:

```tsx
import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { forceRefresh } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState } from "../lib/types";
import { BriefView } from "./brief/BriefView";
import { ChatPanel } from "./components/ChatPanel";
import { ProjectsView } from "./projects/ProjectsView";

type Tab = "brief" | "projects";

export function App() {
  const [tab, setTab] = useState<Tab>("brief");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  // Increment whenever the backend settles after a refresh — BriefView reloads.
  const [agentSignal, setAgentSignal] = useState(0);

  useEffect(() => {
    const sub = subscribeAgentState((s) => {
      setAgentState(s);
      if (s === "idle" || s === "alert") setAgentSignal((n) => n + 1);
    });
    return () => sub.close();
  }, []);

  const refresh = async () => {
    try { await forceRefresh(); } catch (e) { console.error(e); }
  };

  const closeWindow = () => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[dashboard] toggle_main failed:", e),
    );
  };

  return (
    <div className="min-h-screen w-full bg-irma-bg text-irma-text flex flex-col">
      <div
        data-tauri-drag-region
        className="h-10 flex items-center justify-between px-4 border-b border-irma-border bg-irma-surface shrink-0"
      >
        <div className="flex items-center gap-3 select-none">
          <StateDot state={agentState} />
          <span className="text-sm font-medium tracking-wide">Irma</span>
          <nav className="flex gap-1 ml-2">
            <TabButton current={tab} id="brief"    onClick={setTab} label="Brief" />
            <TabButton current={tab} id="projects" onClick={setTab} label="Projects" />
          </nav>
          <span className="text-xs text-irma-mute font-mono ml-2">{agentState}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void refresh()} type="button"
                  className="text-xs text-irma-mute hover:text-irma-text px-2 py-0.5 rounded border border-irma-border">
            refresh
          </button>
          <button onClick={closeWindow} type="button" aria-label="Hide window"
                  className="text-base leading-none text-irma-mute hover:text-irma-text px-2 py-0.5 rounded">
            ×
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="max-w-4xl mx-auto space-y-6">
          {tab === "brief" ? <BriefView agentSignal={agentSignal} /> : <ProjectsView />}
          <ChatPanel />
        </div>
      </div>
    </div>
  );
}

function TabButton({
  current, id, onClick, label,
}: { current: Tab; id: Tab; onClick: (t: Tab) => void; label: string }) {
  const active = current === id;
  return (
    <button
      type="button"
      onClick={() => onClick(id)}
      className={
        "px-2 py-0.5 text-xs rounded " +
        (active ? "bg-irma-surface text-irma-text border border-irma-border" : "text-irma-mute hover:text-irma-text")
      }
    >
      {label}
    </button>
  );
}

function StateDot({ state }: { state: AgentState }) {
  const color =
    state === "alert" ? "bg-irma-amber"
    : state === "thinking" ? "bg-irma-violet"
    : state === "observing" ? "bg-irma-teal"
    : "bg-irma-indigo";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}
```

- [ ] **Step 2: Delete obsolete files**

```bash
git rm apps/desktop/src/main/StandupView.tsx apps/desktop/src/main/mockBrief.ts
```

The old per-component `BriefHeader`, `BlockerList`, `ScheduleList`, `Narrative`, `ConflictList` under `main/components/` are now only referenced by the deleted `StandupView`. Inspect the directory and delete any unused files:

```bash
ls apps/desktop/src/main/components/
```

Delete `BriefHeader.tsx`, `BlockerList.tsx`, `ScheduleList.tsx`, and the old `components/Narrative.tsx` / `components/ConflictList.tsx` if they are no longer imported (verify with `git grep` first). Keep `ChatPanel.tsx`.

- [ ] **Step 3: TypeScript check**

```bash
cd apps/desktop && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src/main/
git commit -m "$(cat <<'EOF'
feat(desktop): rewrite App.tsx with Brief/Projects tabs

Header has a tab switcher. BriefView is the default. SSE-driven
agentSignal increments on idle/alert so BriefView reloads after a
backend refresh. StandupView + mockBrief + dead sub-components are
removed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.6: Manual verification

- [ ] **Step 1: Start the backend**

```bash
cd services/api && uv run uvicorn irma_api.main:app --factory --reload --port 8765
```

- [ ] **Step 2: Start the desktop dev server**

```bash
cd apps/desktop && npm run dev
```

- [ ] **Step 3: Verify the golden path**

In the browser at the Vite-reported URL for the dashboard:

1. Header shows `Brief | Projects` tabs and the state dot.
2. **Brief tab — empty state.** With no projects, `Today` renders a stub recommendation ("Add a project to get started."). The four horizon tabs all render without error.
3. **Projects tab.** Click `+ new project`, create "Thesis" with priority 1, target 2026-07-15, goals "Submit draft". Save.
4. The new project appears selected on the right.
5. Click `+ add task`, enter "Draft results", due 2026-05-28, save. The row appears.
6. Click the row title — inline panel expands. Change status to `doing`, blur out — row updates.
7. Tick the row's checkbox — strike-through, status flips to `done`.
8. Switch to `Brief → Today`. The new Brief includes the task you added.
9. Tick the task checkbox in the brief — it disappears from `Focus`; reload is automatic.
10. Switch to `Projects`, delete the empty-task project; verify 204 succeeds.

- [ ] **Step 4: Verify error paths**

1. Stop the backend; reload Brief — the view shows `Brief unavailable: …`.
2. Restart backend, refresh — Brief returns.

- [ ] **Step 5: Commit any UI fixes**

If verification surfaces small bugs (typos, missing imports, layout glitches), fix them and commit:

```bash
git add apps/desktop/src/main
git commit -m "fix(desktop): UI tweaks from manual verification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

If no fixes are needed, skip this step.

---

## Phase 7 — Documentation + final verification

Two tasks. Updates CLAUDE.md to match the new shape and runs a final sweep across lint + types + tests.

### Task 7.1: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update §5 — Core Abstractions**

Replace the existing bullets with:

```markdown
- **`Signal`** — normalized unit every observer emits: `source`, `kind`, `title`, `detail`, `ts`, `meta`. Persisted with optional `project_id` (calendar signals are attributed via project keyword match at write time).
- **`Project`** — first-class manual entity grouping `goals[]`, `target_date`, `calendar_keywords[]`, `priority`, `status (active/paused/archived)`.
- **`Task`** — manually entered work item scoped to a `Project`. Carries `status (todo/doing/done/blocked)`, `due_date`, `scheduled_for`, `estimated_minutes`, auto-stamped `completed_at`.
- **`Observer` protocol** — `async def collect(self) -> list[Signal]`. `TimeAgent` ships; `CodebaseAgent` is gated off behind `IRMA_CODEBASE_AGENT_ENABLED` pending an SSH-aware variant.
- **`LeadAgent`** — horizon-aware synthesizer. `synthesize(horizon: "day"|"week"|"month"|"all") -> Brief`. Builds a per-window context (active projects + tasks in window + recent calendar signals), composes the Irma persona prompt, calls `LLMClient.complete`, parses + caches.
- **`Brief`** — horizon-aware output: `focus[]`, `project_status[]`, `conflicts[]`, `recommendation`, `narrative`. Empty sections hide in the UI.
- **`BriefCacheRepo`** — per-horizon cache row, keyed on `inputs_hash` over project+task+signal state.
- **`AgentState` bus** — unchanged: `idle/observing/thinking/alert` via SSE.
```

- [ ] **Step 2: Update §6 — API Surface**

Replace the table with:

```markdown
| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/projects`              | List projects (`?status=` repeatable; default `active`). |
| POST   | `/api/v1/projects`              | Create project. 409 on duplicate name. |
| GET    | `/api/v1/projects/{id}`         | Get project. 404 if missing. |
| PATCH  | `/api/v1/projects/{id}`         | Partial update. |
| DELETE | `/api/v1/projects/{id}`         | Delete. 409 if non-`done` tasks remain (archive instead). |
| GET    | `/api/v1/tasks`                 | List with filters: `project_id`, `status`, `scheduled_from/to`, `due_before`. |
| POST   | `/api/v1/tasks`                 | Create. 404 if project missing. |
| GET    | `/api/v1/tasks/{id}`            | Get. |
| PATCH  | `/api/v1/tasks/{id}`            | Partial update. `status=done` auto-stamps `completed_at`. |
| DELETE | `/api/v1/tasks/{id}`            | Delete. |
| POST   | `/api/v1/tasks/{id}/complete`   | Idempotent shortcut. |
| GET    | `/api/v1/brief/today`           | Day horizon. Lazy cache on `inputs_hash`. |
| GET    | `/api/v1/brief/week`            | Week horizon. |
| GET    | `/api/v1/brief/month`           | Month horizon. |
| GET    | `/api/v1/brief/overview`        | No-window snapshot across all active projects. |
| POST   | `/api/v1/refresh`               | Force observers; clears `brief_cache`. |
| GET    | `/api/v1/signals`               | Raw signals (debug). |
| GET    | `/api/v1/state`                 | Current `AgentState`. |
| GET    | `/api/v1/stream`                | SSE stream of `AgentState`. |
```

- [ ] **Step 3: Update §9 — Phases**

Append:

```markdown
- **Phase 4 — Manual PMO (this slice).** Project + Task entities, horizon-aware `Brief`, minimal dashboard (`Brief` + `Projects` tabs). `/standup` removed. `CodebaseAgent` gated off (`IRMA_CODEBASE_AGENT_ENABLED=false`).
- **Phase 5 — DEFERRED.** Outbound channels (Gmail API, native notifications), scheduled digests (daily/weekly/monthly auto-email), reminder engine, local-LLM synthesis (gpt-oss on Mac GPU), calendar write-ops, SSH-aware codebase observer.
```

The original Phase 4 line ("ChromaDB RAG…") is now historical context — leave it but rename it to "Phase 4 — Originally planned (superseded by current Phase 4 above)."

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: update CLAUDE.md for manual PMO slice

Refreshes §5 (abstractions), §6 (API surface), §9 (phases) to match
the Project+Task+horizon-aware Brief shape. Original Phase 4 (ChromaDB
RAG etc.) is relabeled as superseded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7.2: Final sweep — lint, type-check, test, manual

**Files:** none (verification only)

- [ ] **Step 1: Backend full pass**

```bash
cd services/api && uv run ruff check . && uv run ruff format --check . && uv run mypy --strict src/irma_api && uv run pytest -q
```

Expected: all green. If ruff format reports diffs, run `uv run ruff format .` and commit:

```bash
git add -u && git commit -m "chore(api): ruff format

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 2: Frontend pass**

```bash
cd apps/desktop && npx tsc --noEmit && npm run build
```

Expected: tsc clean, Vite build succeeds.

- [ ] **Step 3: End-to-end smoke test**

Re-run the Task 6.6 verification flow against a freshly-built backend + dashboard. Confirm:
- Creating + editing + deleting projects and tasks all round-trip via the API.
- All four horizon briefs render — `Today` with a fresh task, `Week` with a scheduled task on a future day, `Month` with `target_date` proximity, `Overview` listing active projects.
- Toggling `IRMA_CODEBASE_AGENT_ENABLED=true` in `.env` and restarting confirms the agent re-registers (verify in startup logs).

- [ ] **Step 4: Final commit if any clean-ups land**

```bash
git status
# If anything remains:
git add -u
git commit -m "chore: final cleanup from end-to-end verification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Done

When all 22 tasks across 7 phases are complete, you should have:

- A SQLite store with `project`, `task`, `brief_cache` tables and `signals.project_id` attribution.
- Full CRUD HTTP surface for `/projects`, `/tasks`, and `/brief/{today,week,month,overview}`.
- A rewritten `LeadAgent` that produces horizon-aware Briefs, cached per horizon, with one-retry JSON parsing.
- The old `/standup` endpoint and `StandupBrief` shape removed.
- A two-tab dashboard (`Brief` + `Projects`) wired end-to-end, reactive to `AgentState` SSE.
- `CodebaseAgent` quiescent behind a config flag.
- `CLAUDE.md` updated to match.

The next slice (deferred, separate spec) takes over: outbound channels (Gmail + macOS notifications), scheduled digests, reminders, and the local-LLM synthesizer swap.
