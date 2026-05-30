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
                "status": {
                    "type": "string",
                    "enum": [s.value for s in ProjectStatus],
                    "description": "Optional status. Defaults to 'active'.",
                },
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
            raise ToolError(
                "invalid_args",
                detail="; ".join(
                    f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
                    for err in exc.errors()
                ),
            ) from exc

        repo = ProjectRepo(self._store.connection)
        try:
            created = await repo.create(payload)
        except ConflictError as exc:
            raise ToolError("conflict", detail=str(exc)) from exc
        return f"created project {created.id} {created.name}"


# Module-level sanity: both classes conform to Tool.
_list_projects_sanity: Tool = ListProjectsTool.__new__(ListProjectsTool)
_create_project_sanity: Tool = CreateProjectTool.__new__(CreateProjectTool)
