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
