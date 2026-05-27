"""Async SQLite-backed persistence for signals + brief cache."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from nofari_api.models.brief import StandupBrief
from nofari_api.models.signal import Signal
from nofari_api.store.migrations import ensure_schema


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def compute_signal_set_hash(signals: Iterable[Signal]) -> str:
    """Stable hash over a set of signals — order-independent."""
    hashes = sorted(s.hash_key() for s in signals)
    blob = "\n".join(hashes).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class SignalStore:
    """Owns a single aiosqlite connection for the process lifetime."""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = aiosqlite.Row
        await ensure_schema(self._conn)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SignalStore not connected — call .connect() first")
        return self._conn

    # --- Signals -------------------------------------------------------------

    async def upsert_signals(self, signals: list[Signal]) -> int:
        """Insert new signals (by hash_key). Returns count of NEW rows."""
        if not signals:
            return 0
        conn = self._require()
        rows = [
            (
                s.source,
                s.kind,
                s.title,
                s.detail,
                s.ts.isoformat(),
                json.dumps(s.meta, sort_keys=True, default=str),
                s.hash_key(),
                _iso_now(),
            )
            for s in signals
        ]
        cur = await conn.executemany(
            """
            INSERT OR IGNORE INTO signals
                (source, kind, title, detail, ts, meta_json, hash_key, collected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await conn.commit()
        # `rowcount` from executemany is the total number of changes, which
        # equals the count of newly inserted rows (IGNORE no-ops contribute 0).
        return cur.rowcount or 0

    async def latest_signals(self, limit: int = 500) -> list[Signal]:
        conn = self._require()
        cur = await conn.execute(
            "SELECT source, kind, title, detail, ts, meta_json "
            "FROM signals "
            "ORDER BY datetime(ts) DESC "
            "LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [self._row_to_signal(r) for r in rows]

    @staticmethod
    def _row_to_signal(row: aiosqlite.Row) -> Signal:
        meta_raw = row["meta_json"]
        meta: dict[str, Any] = json.loads(meta_raw) if meta_raw else {}
        return Signal(
            source=row["source"],
            kind=row["kind"],
            title=row["title"],
            detail=row["detail"] or "",
            ts=datetime.fromisoformat(row["ts"]),
            meta=meta,
        )

    # --- Briefs --------------------------------------------------------------

    async def get_cached_brief(self, signal_set_hash: str) -> StandupBrief | None:
        conn = self._require()
        cur = await conn.execute(
            "SELECT payload_json FROM briefs WHERE signal_set_hash = ?",
            (signal_set_hash,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return StandupBrief.model_validate_json(row["payload_json"])

    async def cache_brief(self, signal_set_hash: str, brief: StandupBrief) -> None:
        conn = self._require()
        await conn.execute(
            """
            INSERT OR REPLACE INTO briefs (signal_set_hash, payload_json, generated_at)
            VALUES (?, ?, ?)
            """,
            (signal_set_hash, brief.model_dump_json(), brief.generated_at.isoformat()),
        )
        await conn.commit()

    async def invalidate_briefs(self) -> None:
        """Drop the entire brief cache. Called from POST /refresh."""
        conn = self._require()
        await conn.execute("DELETE FROM briefs")
        await conn.commit()
