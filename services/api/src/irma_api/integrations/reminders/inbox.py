"""Ensure the auto-managed Inbox project exists.

Called at the top of every sync — re-creates the Inbox row if the user
manually deleted it, since the planner needs a target for phone-captured
reminders that land in the `Irma · Inbox` calendar.
"""

from __future__ import annotations

from irma_api.models.project import Project, ProjectCreate, ProjectStatus
from irma_api.store.errors import ConflictError
from irma_api.store.repos.project_repo import ProjectRepo

INBOX_NAME = "Inbox"
INBOX_DESCRIPTION = "Auto-created. Triage items captured from phone."


async def ensure_inbox_project(repo: ProjectRepo) -> Project:
    """Return the Inbox project, creating it idempotently if missing."""

    existing = [
        p
        for p in await repo.list(
            statuses=[
                ProjectStatus.ACTIVE,
                ProjectStatus.PAUSED,
                ProjectStatus.ARCHIVED,
            ]
        )
        if p.name == INBOX_NAME
    ]
    if existing:
        return existing[0]
    try:
        return await repo.create(
            ProjectCreate(
                name=INBOX_NAME,
                description=INBOX_DESCRIPTION,
                status=ProjectStatus.ACTIVE,
                priority=3,
            )
        )
    except ConflictError:
        # Race: someone else created it between our list and our create.
        again = [
            p
            for p in await repo.list(statuses=[ProjectStatus.ACTIVE])
            if p.name == INBOX_NAME
        ]
        if not again:
            raise
        return again[0]
