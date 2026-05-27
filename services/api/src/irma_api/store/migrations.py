"""Idempotent schema bootstrap. Called once during app lifespan startup."""

from __future__ import annotations

import aiosqlite

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS signals (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        source        TEXT    NOT NULL,
        kind          TEXT    NOT NULL,
        title         TEXT    NOT NULL,
        detail        TEXT    NOT NULL DEFAULT '',
        ts            TEXT    NOT NULL,
        meta_json     TEXT    NOT NULL DEFAULT '{}',
        hash_key      TEXT    NOT NULL UNIQUE,
        collected_at  TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signals_source_kind ON signals(source, kind)",
    "CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts)",
    """
    CREATE TABLE IF NOT EXISTS briefs (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_set_hash   TEXT    NOT NULL UNIQUE,
        payload_json      TEXT    NOT NULL,
        generated_at      TEXT    NOT NULL
    )
    """,
)


async def ensure_schema(conn: aiosqlite.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        await conn.execute(statement)
    await conn.commit()
