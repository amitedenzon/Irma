"""HTTP surface for Project CRUD."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse

from irma_api.models.project import (
    Project,
    ProjectCreate,
    ProjectStatus,
    ProjectUpdate,
)
from irma_api.routers.integrations import _trigger_reminder_sync
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
    status: list[ProjectStatus] | None = Query(default=None),
) -> list[Project]:
    return await _repo(request).list(statuses=status)


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: Request, payload: ProjectCreate
) -> Project | JSONResponse:
    try:
        result = await _repo(request).create(payload)
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return result


@router.get("/{project_id}", response_model=Project)
async def get_project(request: Request, project_id: str) -> Project | JSONResponse:
    try:
        return await _repo(request).get(project_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))


@router.patch("/{project_id}", response_model=Project)
async def update_project(
    request: Request, project_id: str, patch: ProjectUpdate
) -> Project | JSONResponse:
    try:
        result = await _repo(request).update(project_id, patch)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return result


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(request: Request, project_id: str) -> Response:
    try:
        await _repo(request).delete(project_id)
    except NotFoundError as exc:
        return _err(404, "not_found", str(exc))
    except ConflictError as exc:
        return _err(409, "conflict", str(exc))
    _trigger_reminder_sync(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
