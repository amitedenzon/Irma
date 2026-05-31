"""End-to-end smoke test against the real macOS Reminders database.

Run with:
    cd services/api
    IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py -v

Uses a unique calendar prefix per run (e.g. `IrmaTest-abc12345 · `) so it
won't touch the user's real `Irma · *` lists. Tears down all calendars
matching the prefix on exit.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import aiosqlite
import pytest

from irma_api.integrations.reminders.bridge import ReminderBridge
from irma_api.integrations.reminders.sync import ReminderSyncService
from irma_api.models.project import ProjectCreate
from irma_api.models.task import TaskCreate
from irma_api.store.migrations import ensure_schema
from irma_api.store.repos.project_repo import ProjectRepo
from irma_api.store.repos.task_repo import TaskRepo

pytestmark = pytest.mark.skipif(
    not os.environ.get("IRMA_REMINDERS_E2E"),
    reason="set IRMA_REMINDERS_E2E=1 to run end-to-end Reminders tests",
)

REPO_ROOT = Path(__file__).resolve().parents[4]
HELPER = REPO_ROOT / "tools" / "reminders-helper" / "bin" / "irma-reminders-helper"


@pytest.mark.asyncio
async def test_full_push_creates_per_project_calendars(tmp_path) -> None:
    assert HELPER.exists(), f"build the helper first: {HELPER}"
    test_prefix = f"IrmaTest-{uuid.uuid4().hex[:8]} · "

    bridge = ReminderBridge(binary_path=HELPER)
    status = await bridge.access_status()
    if status != "authorized":
        granted = await bridge.request_access()
        if not granted:
            pytest.skip(f"reminders access status={status}; user must grant access")

    created_ids: list[str] = []
    try:
        async with aiosqlite.connect(tmp_path / "e2e.db") as conn:
            conn.row_factory = aiosqlite.Row
            await ensure_schema(conn)
            projects = ProjectRepo(conn)
            tasks = TaskRepo(conn)
            p = await projects.create(ProjectCreate(name="Alpha"))
            await tasks.create(TaskCreate(project_id=p.id, title="e2e task"))

            svc = ReminderSyncService(
                project_repo=projects, task_repo=tasks,
                bridge=bridge, calendar_prefix=test_prefix,
            )
            await svc.sync_once()  # Phase 1: ensures calendars
            await svc.sync_once()  # Phase 2: pushes the task

            cals = await bridge.list_calendars(test_prefix)
            created_ids = [c.calendar_id for c in cals]
            titles = sorted(c.title for c in cals)
            assert titles == [test_prefix + "Alpha", test_prefix + "Inbox"]

            alpha = next(c for c in cals if c.title == test_prefix + "Alpha")
            rems = await bridge.list(alpha.calendar_id)
            assert any(r.title == "e2e task" for r in rems)
    finally:
        for cid in created_ids:
            try:
                await bridge.delete_calendar(cid)
            except Exception:
                pass
