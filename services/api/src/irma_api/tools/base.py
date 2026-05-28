"""Tool abstraction consumed by the LLM tool-call loop.

A Tool is an async callable with a JSON-Schema-described interface. The
chat router runs the loop; the registry just dispatches by name.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class ToolSpec(BaseModel):
    """Provider-agnostic tool description.

    `input_schema` is a JSON Schema object; both Anthropic and Ollama accept
    this shape with minor wire-level wrapping.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolError(Exception):
    """Raised by tools (and the registry) on user-visible failure paths."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@runtime_checkable
class Tool(Protocol):
    """The interface every registered tool implements."""

    spec: ToolSpec

    async def call(self, args: dict[str, Any]) -> str: ...


class ToolRegistry:
    """Name-indexed dispatch for registered tools."""

    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {t.spec.name: t for t in tools}

    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    async def call(self, name: str, args: dict[str, Any]) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError("tool_not_found", detail=f"no tool named {name!r}")
        return await tool.call(args)
