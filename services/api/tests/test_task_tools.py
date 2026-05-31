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
    # format is "created task <id> <title>"
    task_id = created_msg.split()[2]

    completer = CompleteTaskTool(store)
    first = await completer.call({"task_id": task_id})
    second = await completer.call({"task_id": task_id})
    assert "completed task" in first
    assert "completed task" in second
    assert task_id in first

    lister = ListTasksTool(store)
    out = await lister.call({"status": ["done"]})
    assert "Ship" in out


@pytest.mark.asyncio
async def test_complete_unknown_task_raises_not_found(store: SignalStore) -> None:
    completer = CompleteTaskTool(store)
    with pytest.raises(ToolError) as exc_info:
        await completer.call({"task_id": "nope"})
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_create_task_invalid_args_detail_is_human_readable(store: SignalStore) -> None:
    pid = await _seed_project(store)
    creator = CreateTaskTool(store)
    with pytest.raises(ToolError) as exc_info:
        await creator.call({"project_id": pid, "title": ""})
    assert exc_info.value.code == "invalid_args"
    detail = exc_info.value.detail or ""
    assert "title" in detail
    assert "validation error" not in detail.lower()
