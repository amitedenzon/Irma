"""ToolRegistry dispatch and error surface."""

from __future__ import annotations

from typing import Any

import pytest

from irma_api.tools.base import Tool, ToolError, ToolRegistry, ToolSpec


class _StubTool:
    spec = ToolSpec(
        name="echo",
        description="Echo the input back.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )

    async def call(self, args: dict[str, Any]) -> str:
        return f"echo:{args['text']}"


@pytest.mark.asyncio
async def test_registry_lists_specs() -> None:
    registry = ToolRegistry([_StubTool()])
    specs = registry.specs()
    assert len(specs) == 1
    assert specs[0].name == "echo"


@pytest.mark.asyncio
async def test_registry_call_dispatches() -> None:
    registry = ToolRegistry([_StubTool()])
    result = await registry.call("echo", {"text": "hi"})
    assert result == "echo:hi"


@pytest.mark.asyncio
async def test_registry_call_unknown_tool_raises() -> None:
    registry = ToolRegistry([_StubTool()])
    with pytest.raises(ToolError) as exc_info:
        await registry.call("nope", {})
    assert exc_info.value.code == "tool_not_found"


def test_tool_protocol_is_runtime_checkable() -> None:
    assert isinstance(_StubTool(), Tool)


def test_empty_registry_specs_is_empty_list() -> None:
    assert ToolRegistry([]).specs() == []
