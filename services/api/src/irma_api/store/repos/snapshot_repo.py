"""Async access for the `daily_snapshot` table.

One row per local calendar day, keyed by ISO date. Stores per-project open/done
task counts and the set of completed task ids as of that snapshot, so the daily
brief can compute day-over-day progress against the most recent prior row.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import aiosqlite


@dataclass(frozen=True)
class DailySnapshot:
    snapshot_date: date
    per_project_counts: dict[str, dict[str, int]]
    completed_task_ids: list[str]
    created_at: datetime


def _row_to_snapshot(row: aiosqlite.Row) -> DailySnapshot:
    return DailySnapshot(
        snapshot_date=date.fromisoformat(row["snapshot_date"]),
        per_project_counts=json.loads(row["per_project_counts"]),
        completed_task_ids=json.loads(row["completed_task_ids"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SnapshotRepo:
    """Pure data access for `daily_snapshot` rows."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def upsert(
        self,
        snapshot_date: date,
        *,
        per_project_counts: dict[str, dict[str, int]],
        completed_task_ids: list[str],
    ) -> None:
        await self._conn.execute(
            """
            INSERT OR REPLACE INTO daily_snapshot
                (snapshot_date, per_project_counts, completed_task_ids, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                snapshot_date.isoformat(),
                json.dumps(per_project_counts),
                json.dumps(completed_task_ids),
                datetime.now(UTC).replace(microsecond=0).isoformat(),
            ),
        )
        await self._conn.commit()

    async def get(self, snapshot_date: date) -> DailySnapshot | None:
        cur = await self._conn.execute(
            "SELECT * FROM daily_snapshot WHERE snapshot_date = ?",
            (snapshot_date.isoformat(),),
        )
        row = await cur.fetchone()
        return _row_to_snapshot(row) if row else None

    async def latest_before(self, snapshot_date: date) -> DailySnapshot | None:
        cur = await self._conn.execute(
            """
            SELECT * FROM daily_snapshot
            WHERE snapshot_date < ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (snapshot_date.isoformat(),),
        )
        row = await cur.fetchone()
        return _row_to_snapshot(row) if row else None
