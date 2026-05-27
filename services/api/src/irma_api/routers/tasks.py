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
