"""Idempotent schema bootstrap. Called once during app lifespan startup.

Strategy: additive `CREATE TABLE IF NOT EXISTS` for all tables, plus a
single targeted `ALTER TABLE signals ADD COLUMN project_id` guarded by a
column-existence check so re-runs are safe. The old `briefs` table is
dropped explicitly because its cache key (`signal_set_hash`) is
incompatible with the new horizon-keyed `brief_cache`.
"""

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
        collected_at  TEXT    NOT NULL,
        project_id    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_signals_source_kind ON signals(source, kind)",
    "CREATE INDEX IF NOT EXISTS idx_signals_ts          ON signals(ts)",
    """
    CREATE TABLE IF NOT EXISTS project (
        id                 TEXT    PRIMARY KEY,
        name               TEXT    NOT NULL,
        name_lower         TEXT    NOT NULL UNIQUE,
        description        TEXT    NOT NULL DEFAULT '',
        status             TEXT    NOT NULL DEFAULT 'active',
        priority           INTEGER NOT NULL DEFAULT 2,
        calendar_keywords  TEXT    NOT NULL DEFAULT '[]',
        goals              TEXT    NOT NULL DEFAULT '[]',
        target_date        TEXT,
        created_at         TEXT    NOT NULL,
        updated_at         TEXT    NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_project_status_priority "
    "ON project(status, priority, name_lower)",
    """
    CREATE TABLE IF NOT EXISTS task (
        id                 TEXT    PRIMARY KEY,
        project_id         TEXT    NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
        title              TEXT    NOT NULL,
        notes              TEXT    NOT NULL DEFAULT '',
        status             TEXT    NOT NULL DEFAULT 'todo',
        due_date           TEXT,
        scheduled_for      TEXT,
        estimated_minutes  INTEGER,
        created_at         TEXT    NOT NULL,
        updated_at         TEXT    NOT NULL,
        completed_at       TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_project       ON task(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_task_scheduled     ON task(scheduled_for)",
    "CREATE INDEX IF NOT EXISTS idx_task_due_status    ON task(due_date, status)",
    """
    CREATE TABLE IF NOT EXISTS brief_cache (
        horizon       TEXT PRIMARY KEY
            CHECK (horizon IN ('day','week','month','all')),
        payload_json  TEXT NOT NULL,
        inputs_hash   TEXT NOT NULL,
        computed_at   TEXT NOT NULL
    )
    """,
    "DROP TABLE IF EXISTS briefs",
)


async def _signals_has_project_id(conn: aiosqlite.Connection) -> bool:
    cur = await conn.execute("PRAGMA table_info(signals)")
    return any(row[1] == "project_id" for row in await cur.fetchall())


async def ensure_schema(conn: aiosqlite.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        await conn.execute(statement)

    if not await _signals_has_project_id(conn):
        await conn.execute("ALTER TABLE signals ADD COLUMN project_id TEXT")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signals_project_id "
        "ON signals(project_id)"
    )
    await conn.commit()
