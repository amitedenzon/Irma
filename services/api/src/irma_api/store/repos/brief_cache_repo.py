"""Per-horizon brief cache. One row per horizon; replace-on-write."""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from irma_api.models.brief import Brief, Horizon


class BriefCacheRepo:
    """A tiny key/value layer keyed on `horizon`."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def get(self, horizon: Horizon, *, inputs_hash: str) -> Brief | None:
        cur = await self._conn.execute(
            "SELECT payload_json, inputs_hash FROM brief_cache WHERE horizon = ?",
            (horizon,),
        )
        row = await cur.fetchone()
        if row is None or row["inputs_hash"] != inputs_hash:
            return None
        return Brief.model_validate_json(row["payload_json"])

    async def put(self, horizon: Horizon, *, inputs_hash: str, brief: Brief) -> None:
        await self._conn.execute(
            """
            INSERT INTO brief_cache (horizon, payload_json, inputs_hash, computed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(horizon) DO UPDATE SET
                payload_json = excluded.payload_json,
                inputs_hash  = excluded.inputs_hash,
                computed_at  = excluded.computed_at
            """,
            (
                horizon,
                brief.model_dump_json(),
                inputs_hash,
                datetime.now(UTC).isoformat(),
            ),
        )
        await self._conn.commit()

    async def clear(self) -> None:
        await self._conn.execute("DELETE FROM brief_cache")
        await self._conn.commit()
