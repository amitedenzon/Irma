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


def _summarize_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
        for err in exc.errors()
    )


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


def _format_task_line(
    task_id: str,
    status: str,
    title: str,
    project_id: str,
    due: date | None,
    scheduled: date | None,
) -> str:
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
            "scheduled window. Defaults to all tasks across all projects."
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
            raise ToolError("invalid_args", detail=_summarize_validation_error(exc)) from exc

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
