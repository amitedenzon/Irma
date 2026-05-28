# Chat Backend Parity + Read/Write Tools — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chat tab expose two backends ("Local" and "Claude") with identical abilities: read + write Google Calendar, read + write Projects + Tasks, send email to self.

**Architecture:** Reuse the existing `ToolRegistry` + tool-call loop in `routers/chat.py`. Add six new `Tool` implementations (one calendar-write + two project + three task). Hide `claude_cli` server-side from `/chat/backends` (it skips the tool loop and can't host these). Bump the Google OAuth scope from `calendar.readonly` → `calendar.events` so writes work.

**Tech Stack:** Python 3.12 / FastAPI / aiosqlite / aiogoogle / Pydantic v2 / pytest-asyncio. React + TypeScript for the one-line UI label change.

**Spec:** `docs/superpowers/specs/2026-05-28-chat-tools-parity-design.md`

---

## File map

| File | Status | Purpose |
| ---- | ------ | ------- |
| `services/api/src/irma_api/auth/google_oauth.py` | modify | bump `SCOPES` to `calendar.events` |
| `services/api/src/irma_api/agents/time_agent.py` | modify | match new scope in `_build_creds` |
| `services/api/src/irma_api/tools/calendar.py` | modify | update `ReadCalendarTool._build_creds` scope + add `CreateCalendarEventTool` |
| `services/api/src/irma_api/tools/projects.py` | create | `ListProjectsTool`, `CreateProjectTool` |
| `services/api/src/irma_api/tools/tasks.py` | create | `ListTasksTool`, `CreateTaskTool`, `CompleteTaskTool` |
| `services/api/src/irma_api/app.py` | modify | register the six new tools |
| `services/api/src/irma_api/routers/chat.py` | modify | hide `claude_cli` from `/chat/backends`; append tool-list line to `_SYSTEM_PROMPT` |
| `apps/desktop/src/main/chat/ChatView.tsx` | modify | drop `claude_cli` label; rename `anthropic` → "Claude" |
| `services/api/tests/test_calendar_tool.py` | modify | re-cover scope assertion if present (defensive) |
| `services/api/tests/test_create_calendar_event_tool.py` | create | tests for the new write tool |
| `services/api/tests/test_project_tools.py` | create | tests for project tools |
| `services/api/tests/test_task_tools.py` | create | tests for task tools |
| `services/api/tests/test_chat_backends_filter.py` | create | tests that `/chat/backends` hides `claude_cli` |
| `services/api/tests/test_app_boot.py` | modify | extend tool-registry assertion to include new tools |

---

## Working directory

All Python commands assume `cd services/api`. The repo root is the parent.

---

## Task 1: Bump Google OAuth scope

**Files:**
- Modify: `services/api/src/irma_api/auth/google_oauth.py:25-27`
- Modify: `services/api/src/irma_api/agents/time_agent.py:73`
- Modify: `services/api/src/irma_api/tools/calendar.py:79,134`

**Why first:** the new `CreateCalendarEventTool` 403s on writes if the refresh token is still `.readonly`. Bumping the scope first means a single re-auth (run by the user once after deploy) covers both reads and writes.

- [ ] **Step 1: Update the canonical scope list**

Edit `services/api/src/irma_api/auth/google_oauth.py`:

```python
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.events",
)
```

(Replaces the `calendar.readonly` line.)

- [ ] **Step 2: Update `TimeAgent` scope string**

Edit `services/api/src/irma_api/agents/time_agent.py:73` — change `"https://www.googleapis.com/auth/calendar.readonly"` to `"https://www.googleapis.com/auth/calendar.events"`.

- [ ] **Step 3: Update `ReadCalendarTool` scope string and error hint**

Edit `services/api/src/irma_api/tools/calendar.py`:
- Line 134: `"https://www.googleapis.com/auth/calendar.readonly"` → `"https://www.googleapis.com/auth/calendar.events"`.
- Line 79 detail string: `"run \`irma-api auth google\` to grant calendar.readonly"` → `"run \`irma-api auth google\` to grant calendar.events"`.

- [ ] **Step 4: Run the OAuth + calendar tests, fix any string-pinned assertions**

Run: `pytest tests/test_oauth_flow.py tests/test_calendar_tool.py -v`
Expected: all pass. If any test pins the literal `calendar.readonly`, update the literal in the test to `calendar.events` — these are mechanical replacements, no behavior change.

- [ ] **Step 5: Commit**

```bash
git add services/api/src/irma_api/auth/google_oauth.py \
        services/api/src/irma_api/agents/time_agent.py \
        services/api/src/irma_api/tools/calendar.py \
        services/api/tests/
git commit -m "chore(auth): bump Google OAuth scope to calendar.events"
```

Note: the user must re-run `irma-api auth google` once after this lands — the existing refresh token is narrower-scoped and Google will refuse writes against it.

---

## Task 2: `CreateCalendarEventTool`

**Files:**
- Modify: `services/api/src/irma_api/tools/calendar.py` (append new class)
- Create: `services/api/tests/test_create_calendar_event_tool.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_create_calendar_event_tool.py`:

```python
"""CreateCalendarEventTool: spec shape, validation, success path."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from irma_api.config import Settings
from irma_api.tools.base import ToolError
from irma_api.tools.calendar import CreateCalendarEventTool


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "google_oauth_client_id": "cid",
        "google_oauth_client_secret": "sec",
        "google_oauth_refresh_token": "rt",
    }
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


@pytest.mark.asyncio
async def test_spec_requires_summary_start_end() -> None:
    tool = CreateCalendarEventTool(_settings())
    schema = tool.spec.input_schema
    assert {"summary", "start", "end"}.issubset(set(schema["required"]))
    assert {"description", "location"}.isdisjoint(set(schema["required"]))


@pytest.mark.asyncio
async def test_missing_refresh_token_raises_unlinked() -> None:
    tool = CreateCalendarEventTool(_settings(google_oauth_refresh_token=None))
    with pytest.raises(ToolError) as exc_info:
        await tool.call(
            {"summary": "x", "start": "2026-05-28T10:00:00Z", "end": "2026-05-28T11:00:00Z"}
        )
    assert exc_info.value.code == "calendar_unlinked"


@pytest.mark.asyncio
async def test_end_before_start_raises_invalid_args() -> None:
    tool = CreateCalendarEventTool(_settings())
    with pytest.raises(ToolError) as exc_info:
        await tool.call(
            {
                "summary": "x",
                "start": "2026-05-28T12:00:00Z",
                "end": "2026-05-28T11:00:00Z",
            }
        )
    assert exc_info.value.code == "invalid_args"


@pytest.mark.asyncio
async def test_unparseable_start_raises_invalid_args() -> None:
    tool = CreateCalendarEventTool(_settings())
    with pytest.raises(ToolError) as exc_info:
        await tool.call(
            {"summary": "x", "start": "not-a-date", "end": "2026-05-28T11:00:00Z"}
        )
    assert exc_info.value.code == "invalid_args"


@pytest.mark.asyncio
async def test_success_returns_html_link() -> None:
    tool = CreateCalendarEventTool(_settings())
    captured: dict[str, Any] = {}

    async def fake_insert(
        _self: Any, _client: Any, _user: Any, body: dict[str, Any]
    ) -> dict[str, Any]:
        captured["body"] = body
        return {"htmlLink": "https://calendar.example/x"}

    with patch.object(CreateCalendarEventTool, "_insert_event", new=fake_insert):
        out = await tool.call(
            {
                "summary": "Focus block",
                "start": "2026-05-28T10:00:00Z",
                "end": "2026-05-28T12:00:00Z",
                "description": "video model bench",
                "location": "home",
            }
        )

    assert "https://calendar.example/x" in out
    assert captured["body"]["summary"] == "Focus block"
    assert captured["body"]["start"] == {"dateTime": "2026-05-28T10:00:00Z"}
    assert captured["body"]["end"] == {"dateTime": "2026-05-28T12:00:00Z"}
    assert captured["body"]["description"] == "video model bench"
    assert captured["body"]["location"] == "home"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_create_calendar_event_tool.py -v`
Expected: `ImportError: cannot import name 'CreateCalendarEventTool'`

- [ ] **Step 3: Implement `CreateCalendarEventTool`**

Append to `services/api/src/irma_api/tools/calendar.py` (after `ReadCalendarTool`, before the module-level `_: Tool = ...` sanity line — actually below it is fine, add a new sanity line for the new class too):

```python
class CreateCalendarEventTool:
    """Creates an event on the operator's primary Google Calendar."""

    spec = ToolSpec(
        name="create_calendar_event",
        description=(
            "Create an event on the operator's primary Google Calendar. "
            "Times must be RFC3339 (e.g. '2026-05-28T10:00:00Z'). "
            "Use this for scheduling focus blocks, reminders, or meetings."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Event title."},
                "start": {
                    "type": "string",
                    "description": "Start time, RFC3339 (e.g. 2026-05-28T10:00:00Z).",
                },
                "end": {
                    "type": "string",
                    "description": "End time, RFC3339. Must be strictly after start.",
                },
                "description": {"type": "string", "description": "Optional body text."},
                "location": {"type": "string", "description": "Optional location."},
            },
            "required": ["summary", "start", "end"],
            "additionalProperties": False,
        },
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def call(self, args: dict[str, Any]) -> str:
        if not self._has_credentials():
            raise ToolError(
                "calendar_unlinked",
                detail="run `irma-api auth google` to grant calendar.events",
            )

        summary = str(args.get("summary", "")).strip()
        start_raw = str(args.get("start", "")).strip()
        end_raw = str(args.get("end", "")).strip()
        if not summary or not start_raw or not end_raw:
            raise ToolError(
                "invalid_args",
                detail="summary, start, end are required",
            )
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ToolError(
                "invalid_args",
                detail=f"start/end must be RFC3339 timestamps: {exc}",
            ) from exc
        if end_dt <= start_dt:
            raise ToolError("invalid_args", detail="end must be after start")

        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start_raw},
            "end": {"dateTime": end_raw},
        }
        description = str(args.get("description", "")).strip()
        if description:
            body["description"] = description
        location = str(args.get("location", "")).strip()
        if location:
            body["location"] = location

        client, user = self._build_creds()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),
                wait=wait_exponential_jitter(initial=1, max=30),
                retry=retry_if_exception(_is_rate_limited),
                reraise=True,
            ):
                with attempt:
                    created = await self._insert_event(client, user, body)
        except (AuthError, RetryError) as exc:
            logger.warning("create_calendar_event.auth_failed", error=str(exc))
            raise ToolError("calendar_auth_failed", detail=str(exc)) from exc
        except HTTPError as exc:
            status = getattr(getattr(exc, "res", None), "status_code", None)
            logger.warning(
                "create_calendar_event.http_error", status=status, error=str(exc)
            )
            raise ToolError("calendar_http_error", detail=str(exc)) from exc

        link = str(created.get("htmlLink") or "")
        return f"created event {link}".strip()

    # --- internals -----------------------------------------------------------

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
        assert s.google_oauth_client_id is not None
        assert s.google_oauth_client_secret is not None
        assert s.google_oauth_refresh_token is not None
        client = ClientCreds(
            client_id=s.google_oauth_client_id.get_secret_value(),
            client_secret=s.google_oauth_client_secret.get_secret_value(),
            scopes=["https://www.googleapis.com/auth/calendar.events"],
        )
        user = UserCreds(
            refresh_token=s.google_oauth_refresh_token.get_secret_value(),
        )
        return client, user

    async def _insert_event(
        self,
        client: ClientCreds,
        user: UserCreds,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        async with Aiogoogle(user_creds=user, client_creds=client) as g:
            calendar = await g.discover("calendar", "v3")
            req = calendar.events.insert(calendarId="primary", json=body)
            resp = await g.as_user(req)
            return cast(dict[str, Any], resp)


# Module-level sanity: CreateCalendarEventTool conforms to Tool.
_create_calendar_event_tool_sanity: Tool = CreateCalendarEventTool.__new__(
    CreateCalendarEventTool
)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_create_calendar_event_tool.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Lint + type-check**

Run: `ruff check src/irma_api/tools/calendar.py && mypy --strict src/irma_api/tools/calendar.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/tools/calendar.py \
        services/api/tests/test_create_calendar_event_tool.py
git commit -m "feat(tools): add create_calendar_event tool"
```

---

## Task 3: Project tools (`list_projects`, `create_project`)

**Files:**
- Create: `services/api/src/irma_api/tools/projects.py`
- Create: `services/api/tests/test_project_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_project_tools.py`:

```python
"""ListProjectsTool + CreateProjectTool: spec, dispatch, error paths."""

from __future__ import annotations

import pytest

from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import ToolError
from irma_api.tools.projects import CreateProjectTool, ListProjectsTool


@pytest.mark.asyncio
async def test_list_projects_spec_has_optional_status(store: SignalStore) -> None:
    tool = ListProjectsTool(store)
    schema = tool.spec.input_schema
    assert "status" in schema["properties"]
    assert "required" not in schema or schema["required"] == []


@pytest.mark.asyncio
async def test_list_projects_empty_returns_friendly_message(store: SignalStore) -> None:
    tool = ListProjectsTool(store)
    out = await tool.call({})
    assert "No projects" in out


@pytest.mark.asyncio
async def test_create_then_list_round_trip(store: SignalStore) -> None:
    creator = CreateProjectTool(store)
    out = await creator.call({"name": "Video Model", "priority": 1})
    assert "Video Model" in out
    assert "created project" in out

    lister = ListProjectsTool(store)
    listed = await lister.call({})
    assert "Video Model" in listed


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name(store: SignalStore) -> None:
    creator = CreateProjectTool(store)
    await creator.call({"name": "Video Model"})
    with pytest.raises(ToolError) as exc_info:
        await creator.call({"name": "Video Model"})
    assert exc_info.value.code == "conflict"


@pytest.mark.asyncio
async def test_list_projects_rejects_unknown_status(store: SignalStore) -> None:
    tool = ListProjectsTool(store)
    with pytest.raises(ToolError) as exc_info:
        await tool.call({"status": ["bogus"]})
    assert exc_info.value.code == "invalid_args"


@pytest.mark.asyncio
async def test_create_project_with_keywords_and_target_date(store: SignalStore) -> None:
    creator = CreateProjectTool(store)
    out = await creator.call(
        {
            "name": "MIT DL",
            "calendar_keywords": ["mit", "dl"],
            "target_date": "2026-12-31",
            "goals": ["finish coursework"],
        }
    )
    assert "MIT DL" in out
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_project_tools.py -v`
Expected: `ImportError: No module named 'irma_api.tools.projects'`

- [ ] **Step 3: Implement the tools**

Create `services/api/src/irma_api/tools/projects.py`:

```python
"""Project tools: list and create projects from inside /chat."""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from pydantic import ValidationError

from irma_api.models.project import ProjectCreate, ProjectStatus
from irma_api.store.errors import ConflictError
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import Tool, ToolError, ToolSpec

logger = structlog.get_logger(__name__)


def _parse_statuses(raw: Any) -> list[ProjectStatus]:
    if raw is None:
        return [ProjectStatus.ACTIVE]
    if not isinstance(raw, list):
        raise ToolError("invalid_args", detail="`status` must be a list of strings")
    try:
        return [ProjectStatus(s) for s in raw]
    except ValueError as exc:
        raise ToolError("invalid_args", detail=str(exc)) from exc


def _format_project_line(name: str, pid: str, status: str, target: date | None) -> str:
    suffix = f" (target: {target.isoformat()})" if target else ""
    return f"- {pid}  {name}  [{status}]{suffix}"


class ListProjectsTool:
    """List projects, optionally filtered by status."""

    spec = ToolSpec(
        name="list_projects",
        description=(
            "List the operator's projects. Defaults to active projects only. "
            "Use this before referencing a project by id."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [s.value for s in ProjectStatus],
                    },
                    "description": (
                        "Optional status filter. Omit to return only active "
                        "projects."
                    ),
                },
            },
            "additionalProperties": False,
        },
    )

    def __init__(self, store: SignalStore) -> None:
        self._store = store

    async def call(self, args: dict[str, Any]) -> str:
        statuses = _parse_statuses(args.get("status"))
        repo = ProjectRepo(self._store.connection)
        projects = await repo.list(statuses=statuses)
        if not projects:
            return "No projects."
        lines = ["Projects:"]
        lines.extend(
            _format_project_line(p.name, p.id, p.status.value, p.target_date)
            for p in projects
        )
        return "\n".join(lines)


class CreateProjectTool:
    """Create a new project."""

    spec = ToolSpec(
        name="create_project",
        description=(
            "Create a new project. Returns the new project's id and name. "
            "Use sparingly — projects are coarse-grained groupings, not tasks."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name (1-80 chars)."},
                "description": {"type": "string"},
                "priority": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "description": "1 = highest, 3 = lowest. Defaults to 2.",
                },
                "calendar_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lowercase keywords used to attribute calendar events.",
                },
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "target_date": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD), optional.",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    )

    def __init__(self, store: SignalStore) -> None:
        self._store = store

    async def call(self, args: dict[str, Any]) -> str:
        try:
            payload = ProjectCreate.model_validate(args)
        except ValidationError as exc:
            raise ToolError("invalid_args", detail=str(exc)) from exc

        repo = ProjectRepo(self._store.connection)
        try:
            created = await repo.create(payload)
        except ConflictError as exc:
            raise ToolError("conflict", detail=str(exc)) from exc
        return f"created project {created.id} {created.name}"


# Module-level sanity: both classes conform to Tool.
_list_projects_sanity: Tool = ListProjectsTool.__new__(ListProjectsTool)
_create_project_sanity: Tool = CreateProjectTool.__new__(CreateProjectTool)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_project_tools.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Lint + type-check**

Run: `ruff check src/irma_api/tools/projects.py && mypy --strict src/irma_api/tools/projects.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/tools/projects.py \
        services/api/tests/test_project_tools.py
git commit -m "feat(tools): add list_projects + create_project tools"
```

---

## Task 4: Task tools (`list_tasks`, `create_task`, `complete_task`)

**Files:**
- Create: `services/api/src/irma_api/tools/tasks.py`
- Create: `services/api/tests/test_task_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_task_tools.py`:

```python
"""ListTasksTool + CreateTaskTool + CompleteTaskTool."""

from __future__ import annotations

import pytest

from irma_api.models.project import ProjectCreate
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import ToolError
from irma_api.tools.tasks import CompleteTaskTool, CreateTaskTool, ListTasksTool


async def _seed_project(store: SignalStore, name: str = "P") -> str:
    repo = ProjectRepo(store.connection)
    created = await repo.create(ProjectCreate(name=name))
    return created.id


@pytest.mark.asyncio
async def test_create_task_requires_project_and_title(store: SignalStore) -> None:
    tool = CreateTaskTool(store)
    schema = tool.spec.input_schema
    assert {"project_id", "title"}.issubset(set(schema["required"]))


@pytest.mark.asyncio
async def test_create_task_round_trip(store: SignalStore) -> None:
    pid = await _seed_project(store)
    creator = CreateTaskTool(store)
    out = await creator.call({"project_id": pid, "title": "Read paper"})
    assert "Read paper" in out
    assert "created task" in out

    lister = ListTasksTool(store)
    listed = await lister.call({"project_id": pid})
    assert "Read paper" in listed


@pytest.mark.asyncio
async def test_create_task_unknown_project_raises_not_found(store: SignalStore) -> None:
    creator = CreateTaskTool(store)
    with pytest.raises(ToolError) as exc_info:
        await creator.call({"project_id": "nope", "title": "x"})
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_list_tasks_empty_returns_friendly_message(store: SignalStore) -> None:
    tool = ListTasksTool(store)
    out = await tool.call({})
    assert "No tasks" in out


@pytest.mark.asyncio
async def test_list_tasks_status_filter(store: SignalStore) -> None:
    pid = await _seed_project(store)
    creator = CreateTaskTool(store)
    await creator.call({"project_id": pid, "title": "A"})
    await creator.call({"project_id": pid, "title": "B", "status": "blocked"})

    lister = ListTasksTool(store)
    out = await lister.call({"status": ["blocked"]})
    assert "B" in out
    assert "A" not in out


@pytest.mark.asyncio
async def test_complete_task_marks_done_and_is_idempotent(store: SignalStore) -> None:
    pid = await _seed_project(store)
    creator = CreateTaskTool(store)
    created_msg = await creator.call({"project_id": pid, "title": "Ship"})
    # extract the task id: format is "created task <id> <title>"
    task_id = created_msg.split()[2]

    completer = CompleteTaskTool(store)
    first = await completer.call({"task_id": task_id})
    second = await completer.call({"task_id": task_id})
    assert "completed task" in first
    assert "completed task" in second  # idempotent
    assert task_id in first

    # Confirm via list — DONE tasks need explicit status filter.
    lister = ListTasksTool(store)
    out = await lister.call({"status": ["done"]})
    assert "Ship" in out


@pytest.mark.asyncio
async def test_complete_unknown_task_raises_not_found(store: SignalStore) -> None:
    completer = CompleteTaskTool(store)
    with pytest.raises(ToolError) as exc_info:
        await completer.call({"task_id": "nope"})
    assert exc_info.value.code == "not_found"
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_task_tools.py -v`
Expected: `ImportError: No module named 'irma_api.tools.tasks'`

- [ ] **Step 3: Implement the tools**

Create `services/api/src/irma_api/tools/tasks.py`:

```python
"""Task tools: list, create, complete tasks from inside /chat."""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from pydantic import ValidationError

from irma_api.models.task import TaskCreate, TaskStatus, TaskUpdate
from irma_api.store.errors import NotFoundError
from irma_api.store.repos.task_repo import TaskRepo
from irma_api.store.sqlite import SignalStore
from irma_api.tools.base import Tool, ToolError, ToolSpec

logger = structlog.get_logger(__name__)


def _parse_statuses(raw: Any) -> list[TaskStatus] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ToolError("invalid_args", detail="`status` must be a list of strings")
    try:
        return [TaskStatus(s) for s in raw]
    except ValueError as exc:
        raise ToolError("invalid_args", detail=str(exc)) from exc


def _parse_date(raw: Any, field: str) -> date | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolError("invalid_args", detail=f"`{field}` must be an ISO date string")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ToolError("invalid_args", detail=f"`{field}`: {exc}") from exc


def _format_task_line(task_id: str, status: str, title: str, project_id: str,
                      due: date | None, scheduled: date | None) -> str:
    bits = [f"project: {project_id}"]
    if due is not None:
        bits.append(f"due: {due.isoformat()}")
    if scheduled is not None:
        bits.append(f"scheduled: {scheduled.isoformat()}")
    meta = ", ".join(bits)
    return f"- {task_id}  [{status}]  {title}  ({meta})"


class ListTasksTool:
    """List tasks with optional filters."""

    spec = ToolSpec(
        name="list_tasks",
        description=(
            "List tasks, optionally filtered by project, status, due-by, or "
            "scheduled window. Defaults to all non-archived tasks across all "
            "projects."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "status": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [s.value for s in TaskStatus],
                    },
                },
                "due_before": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD).",
                },
                "scheduled_from": {"type": "string", "description": "ISO date."},
                "scheduled_to": {"type": "string", "description": "ISO date."},
            },
            "additionalProperties": False,
        },
    )

    def __init__(self, store: SignalStore) -> None:
        self._store = store

    async def call(self, args: dict[str, Any]) -> str:
        statuses = _parse_statuses(args.get("status"))
        due_before = _parse_date(args.get("due_before"), "due_before")
        scheduled_from = _parse_date(args.get("scheduled_from"), "scheduled_from")
        scheduled_to = _parse_date(args.get("scheduled_to"), "scheduled_to")
        project_id_raw = args.get("project_id")
        project_id = str(project_id_raw) if project_id_raw is not None else None

        repo = TaskRepo(self._store.connection)
        tasks = await repo.list(
            project_id=project_id,
            statuses=statuses,
            scheduled_from=scheduled_from,
            scheduled_to=scheduled_to,
            due_before=due_before,
        )
        if not tasks:
            return "No tasks."
        lines = ["Tasks:"]
        lines.extend(
            _format_task_line(
                t.id, t.status.value, t.title, t.project_id, t.due_date, t.scheduled_for
            )
            for t in tasks
        )
        return "\n".join(lines)


class CreateTaskTool:
    """Create a new task scoped to a project."""

    spec = ToolSpec(
        name="create_task",
        description=(
            "Create a new task on a project. `project_id` must come from "
            "list_projects (call that first if unknown)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "title": {"type": "string"},
                "notes": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [s.value for s in TaskStatus],
                    "description": "Defaults to 'todo'.",
                },
                "due_date": {"type": "string", "description": "ISO date."},
                "scheduled_for": {"type": "string", "description": "ISO date."},
                "estimated_minutes": {"type": "integer", "minimum": 1},
            },
            "required": ["project_id", "title"],
            "additionalProperties": False,
        },
    )

    def __init__(self, store: SignalStore) -> None:
        self._store = store

    async def call(self, args: dict[str, Any]) -> str:
        try:
            payload = TaskCreate.model_validate(args)
        except ValidationError as exc:
            raise ToolError("invalid_args", detail=str(exc)) from exc

        repo = TaskRepo(self._store.connection)
        try:
            created = await repo.create(payload)
        except NotFoundError as exc:
            raise ToolError("not_found", detail=str(exc)) from exc
        return f"created task {created.id} {created.title}"


class CompleteTaskTool:
    """Mark a task done (idempotent)."""

    spec = ToolSpec(
        name="complete_task",
        description=(
            "Mark a task done. Idempotent — re-completing a done task "
            "returns the existing row."
        ),
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    )

    def __init__(self, store: SignalStore) -> None:
        self._store = store

    async def call(self, args: dict[str, Any]) -> str:
        task_id = str(args.get("task_id", "")).strip()
        if not task_id:
            raise ToolError("invalid_args", detail="`task_id` is required")
        repo = TaskRepo(self._store.connection)
        try:
            updated = await repo.update(task_id, TaskUpdate(status=TaskStatus.DONE))
        except NotFoundError as exc:
            raise ToolError("not_found", detail=str(exc)) from exc
        return f"completed task {updated.id} {updated.title}"


# Module-level sanity: all three conform to Tool.
_list_tasks_sanity: Tool = ListTasksTool.__new__(ListTasksTool)
_create_task_sanity: Tool = CreateTaskTool.__new__(CreateTaskTool)
_complete_task_sanity: Tool = CompleteTaskTool.__new__(CompleteTaskTool)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_task_tools.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Lint + type-check**

Run: `ruff check src/irma_api/tools/tasks.py && mypy --strict src/irma_api/tools/tasks.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/tools/tasks.py \
        services/api/tests/test_task_tools.py
git commit -m "feat(tools): add list/create/complete task tools"
```

---

## Task 5: Register the six new tools in `app.py`

**Files:**
- Modify: `services/api/src/irma_api/app.py:34-80`
- Modify: `services/api/tests/test_app_boot.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_app_boot.py` (end of file):

```python
def test_app_registers_project_and_task_tools_unconditionally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project + task tools need only the store, which is always present."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot3.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        names = set(app.state.tools.names())
        assert {"list_projects", "create_project"}.issubset(names)
        assert {"list_tasks", "create_task", "complete_task"}.issubset(names)


def test_app_registers_create_calendar_event_when_oauth_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot4.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "sec")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "rt")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app):
        names = set(app.state.tools.names())
        assert "read_calendar" in names
        assert "create_calendar_event" in names
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_app_boot.py -v`
Expected: the two new tests FAIL (`create_calendar_event` / `list_projects` not in `names`).

- [ ] **Step 3: Wire the tools in `app.py`**

In `services/api/src/irma_api/app.py`:

a. Extend the tool imports near line 35:

```python
from irma_api.tools.calendar import CreateCalendarEventTool, ReadCalendarTool
from irma_api.tools.projects import CreateProjectTool, ListProjectsTool
from irma_api.tools.resend import ResendSendTool
from irma_api.tools.tasks import CompleteTaskTool, CreateTaskTool, ListTasksTool
```

b. Extend the registration block (around line 73, just after the existing `ReadCalendarTool` append) so it reads:

```python
    if settings.google_oauth_refresh_token is not None:
        tools.append(ReadCalendarTool(settings))
        tools.append(CreateCalendarEventTool(settings))
    else:
        logger.info(
            "tools.calendar_disabled",
            missing=["GOOGLE_OAUTH_REFRESH_TOKEN"],
        )

    tools.append(ListProjectsTool(store))
    tools.append(CreateProjectTool(store))
    tools.append(ListTasksTool(store))
    tools.append(CreateTaskTool(store))
    tools.append(CompleteTaskTool(store))

    registry = ToolRegistry(tools)
```

(The previous `tools.read_calendar_disabled` log line is replaced by the broader `tools.calendar_disabled`.)

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_app_boot.py -v`
Expected: all four boot tests PASS (the two new ones plus the two existing).

- [ ] **Step 5: Lint + type-check**

Run: `ruff check src/irma_api/app.py && mypy --strict src/irma_api/app.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/app.py services/api/tests/test_app_boot.py
git commit -m "feat(app): register calendar-write, project, and task tools"
```

---

## Task 6: Hide `claude_cli` from `/chat/backends`

**Files:**
- Modify: `services/api/src/irma_api/routers/chat.py:128-136`
- Create: `services/api/tests/test_chat_backends_filter.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_chat_backends_filter.py`:

```python
"""GET /chat/backends must not expose claude_cli (no tool support)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from irma_api.app import create_app
from irma_api.agents.llm import ChatTurn, TextResult
from irma_api.config import get_settings
from irma_api.tools.base import ToolSpec


class _StubLLM:
    backend = "stub"
    model = "stub-1"

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1500,
        session_id: str | None = None,
    ) -> TextResult:
        del system, messages, tools, max_tokens, session_id
        return TextResult(text="ok")


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "filter.db"))
    monkeypatch.setenv("IRMA_LLM_BACKEND", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("IRMA_USER_EMAIL", raising=False)
    get_settings.cache_clear()
    return create_app()


def test_backends_endpoint_hides_claude_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        # Inject a fake registry containing claude_cli so we can prove the filter works
        # even when the CLI is installed on the host.
        app.state.llm_registry = {
            "ollama": _StubLLM(),
            "anthropic": _StubLLM(),
            "claude_cli": _StubLLM(),
        }
        app.state.default_backend = "claude_cli"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert "claude_cli" not in body["available"]
        assert "claude_cli" not in body["models"]
        # Default is hidden too — must fall back to a visible backend.
        assert body["default"] in body["available"]


def test_backends_endpoint_returns_null_default_when_only_hidden_backends_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    app = _build_app(monkeypatch, tmp_path)
    with TestClient(app) as client:
        app.state.llm_registry = {"claude_cli": _StubLLM()}
        app.state.default_backend = "claude_cli"

        resp = client.get("/api/v1/chat/backends")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] == []
        assert body["default"] is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_chat_backends_filter.py -v`
Expected: both tests FAIL (`claude_cli` still in `available`).

- [ ] **Step 3: Implement the filter**

In `services/api/src/irma_api/routers/chat.py`:

a. Add a constant near the other `Final` constants (around line 33):

```python
# Backends hidden from /chat/backends — they can't host tools (yet) and
# would silently degrade the chat UX. POST /chat still accepts them if
# passed explicitly.
_HIDDEN_BACKENDS: Final[frozenset[str]] = frozenset({"claude_cli"})
```

b. Rewrite `get_backends` to filter:

```python
@router.get("/chat/backends", response_model=BackendInfo)
async def get_backends(request: Request) -> BackendInfo:
    registry: dict[str, LLMClient] = getattr(request.app.state, "llm_registry", {}) or {}
    default: str | None = getattr(request.app.state, "default_backend", None)

    visible = {name: client for name, client in registry.items() if name not in _HIDDEN_BACKENDS}
    if default in _HIDDEN_BACKENDS or default not in visible:
        default = next(iter(visible), None)

    return BackendInfo(
        default=default,
        available=sorted(visible.keys()),
        models={name: client.model for name, client in visible.items()},
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_chat_backends_filter.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Run the broader chat test suite to confirm nothing else broke**

Run: `pytest tests/test_chat_tool_loop.py tests/test_llm_claude_cli.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/irma_api/routers/chat.py \
        services/api/tests/test_chat_backends_filter.py
git commit -m "feat(chat): hide claude_cli from /chat/backends (no tool support)"
```

---

## Task 7: Append tool list to `_SYSTEM_PROMPT`

**Files:**
- Modify: `services/api/src/irma_api/routers/chat.py:36-56`

No new tests — this is a prompt-text change. The tool loop is already covered by `test_chat_tool_loop.py`.

- [ ] **Step 1: Edit the prompt**

In `services/api/src/irma_api/routers/chat.py`, change `_SYSTEM_PROMPT` so its last paragraph reads:

```
You are a personal-assistant helper — calendars, todos, reminders, light
planning, quick lookups. Defer hard reasoning, large code refactors, or
deep technical work to Amit himself or to a stronger model.

You have these tools available: read_calendar, create_calendar_event,
list_projects, create_project, list_tasks, create_task, complete_task,
send_email. Reach for them when a request needs them; do not narrate
the call.
```

(Keep the existing paragraphs above this verbatim. Only the closing paragraph is appended.)

- [ ] **Step 2: Run the chat loop tests**

Run: `pytest tests/test_chat_tool_loop.py -v`
Expected: all pass (no behavior change, just prompt copy).

- [ ] **Step 3: Commit**

```bash
git add services/api/src/irma_api/routers/chat.py
git commit -m "feat(chat): tell the model which tools it has"
```

---

## Task 8: Frontend label change

**Files:**
- Modify: `apps/desktop/src/main/chat/ChatView.tsx:7-15`

- [ ] **Step 1: Edit `BACKEND_LABEL`**

In `apps/desktop/src/main/chat/ChatView.tsx`, replace the `BACKEND_LABEL` constant:

```ts
const BACKEND_LABEL: Record<string, string> = {
  ollama: "Local",
  anthropic: "Claude",
};
```

(`claude_cli` entry removed — it will never appear in `available` after Task 6.)

- [ ] **Step 2: Verify the frontend type-checks and builds**

Run from `apps/desktop`: `npm run build`
Expected: build succeeds (no TS errors).

- [ ] **Step 3: Commit**

```bash
git add apps/desktop/src/main/chat/ChatView.tsx
git commit -m "feat(chat-ui): show backends as 'Local' and 'Claude'"
```

---

## Task 9: Full-suite verification

- [ ] **Step 1: Run the entire backend test suite**

From `services/api`: `pytest -v`
Expected: all tests pass.

- [ ] **Step 2: Lint + type-check the whole backend**

Run: `ruff check . && mypy --strict src/`
Expected: clean.

---

## Task 10: Manual smoke (post-deploy)

This task is run by the operator (user), not by the implementing agent. List it so it doesn't get forgotten.

- [ ] **Step 1: Re-auth Google so the `calendar.events` scope is granted**

Run: `irma-api auth google`
Expected: browser opens, consent screen shows "See and edit events on your calendars", refresh token is written to `.env`.

- [ ] **Step 2: Start the API and desktop app**

```bash
cd services/api && uv run uvicorn irma_api.main:app --reload &
cd apps/desktop && npm run tauri dev
```

- [ ] **Step 3: In the chat tab, confirm the backend toggle shows exactly two buttons: "Local" and "Claude". No "API". No third option.**

- [ ] **Step 4: Send a chat that exercises each tool path** (one per backend, ideally):
  - "What's on my calendar this week?" → expect `read_calendar` invocation, summary reply.
  - "Block 10–11am tomorrow for a focus session." → expect `create_calendar_event` invocation, link in reply.
  - "What projects do I have?" → expect `list_projects`.
  - "Add a task to <project>: read the Sora 2 paper, due Friday." → expect `create_task`.
  - "Mark the Sora 2 paper task done." → expect `complete_task`.
  - "Email me a summary of this week's calendar." → expect `read_calendar` + `send_email`.

If any path silently fails, check `services/api` logs for `chat.tool_error` entries.

---

## Notes for the implementer

- **Test data isolation:** `conftest.py` provides a `store` fixture that gives each test a fresh file-backed `SignalStore`. Use it for all project/task tool tests — never share state across tests.
- **Async patterns:** every tool is `async def call(...)`. Don't introduce sync I/O.
- **Pydantic v2:** use `model_validate` (not `parse_obj`) and `ConfigDict(extra="forbid")` per existing conventions.
- **Error codes:** stick to the kebab-style codes already in use (`invalid_args`, `not_found`, `conflict`, `calendar_unlinked`, `calendar_auth_failed`, `calendar_http_error`). The chat router turns these into `"error: <code> — <detail>"` strings the LLM reads back.
- **No streaming, no concurrency tricks.** Tool calls run serially inside the existing loop in `routers/chat.py`. Don't change that.
