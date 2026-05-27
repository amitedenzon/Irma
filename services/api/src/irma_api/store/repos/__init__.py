"""Async DAO classes. Each repo accepts an aiosqlite.Connection."""

from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

__all__ = ["ProjectRepo", "TaskRepo"]
