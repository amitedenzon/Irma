"""Async SQLite-backed persistence: signals (with project attribution)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from irma_api.models.signal import Signal
from irma_api.store.migrations import ensure_schema


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

    @property
    def connection(self) -> aiosqlite.Connection:
        """Expose the underlying connection so repos can share it."""
        return self._require()

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SignalStore not connected — call .connect() first")
        return self._conn

    # --- Signals -------------------------------------------------------------

    async def upsert_signals(self, signals: list[Signal]) -> int:
        if not signals:
            return 0
        conn = self._require()
        active_projects = await self._fetch_active_projects()
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
                _match_project_id(s, active_projects),
            )
            for s in signals
        ]
        cur = await conn.executemany(
            """
            INSERT OR IGNORE INTO signals
                (source, kind, title, detail, ts, meta_json, hash_key,
                 collected_at, project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        await conn.commit()
        return cur.rowcount or 0

    async def latest_signals(self, limit: int = 500) -> list[Signal]:
        conn = self._require()
        cur = await conn.execute(
            "SELECT source, kind, title, detail, ts, meta_json "
            "FROM signals ORDER BY datetime(ts) DESC LIMIT ?",
            (limit,),
        )
        return [self._row_to_signal(r) for r in await cur.fetchall()]

    async def _fetch_active_projects(self) -> list[tuple[str, list[str]]]:
        """Return [(project_id, keywords_lowercased)] for active projects,
        ordered by (priority ASC, name_lower ASC) so first-match is deterministic.
        """
        conn = self._require()
        cur = await conn.execute(
            "SELECT id, calendar_keywords FROM project "
            "WHERE status = 'active' "
            "ORDER BY priority ASC, name_lower ASC"
        )
        out: list[tuple[str, list[str]]] = []
        for row in await cur.fetchall():
            kws = json.loads(row["calendar_keywords"]) or []
            out.append((row["id"], [str(k).lower() for k in kws]))
        return out

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


def _match_project_id(sig: Signal, projects: list[tuple[str, list[str]]]) -> str | None:
    if sig.source != "calendar":
        return None
    haystack = f"{sig.title} {sig.detail}".lower()
    for pid, kws in projects:
        if any(kw in haystack for kw in kws):
            return pid
    return None
