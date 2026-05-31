"""Schema migration: idempotent, additive, exposes the new tables/columns."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from irma_api.store.migrations import ensure_schema


@pytest.mark.asyncio
async def test_ensure_schema_creates_all_tables(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await conn.execute("PRAGMA foreign_keys=ON")
        await ensure_schema(conn)

        cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = {r[0] for r in await cur.fetchall()}

    assert {"signals", "project", "task", "brief_cache", "daily_snapshot"} <= names
    assert "briefs" not in names  # old cache dropped


@pytest.mark.asyncio
async def test_signals_has_project_id_column(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(signals)")
        cols = {r[1] for r in await cur.fetchall()}
    assert "project_id" in cols


@pytest.mark.asyncio
async def test_ensure_schema_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        await ensure_schema(conn)  # second call must not raise
        cur = await conn.execute("SELECT COUNT(*) FROM project")
        assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_ensure_schema_adds_project_id_to_existing_signals_db(
    tmp_path: Path,
) -> None:
    """Simulates upgrading a pre-existing DB created from the old schema."""
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        # Old-shape signals table without project_id.
        await conn.execute(
            """
            CREATE TABLE signals (
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
            """
        )
        await conn.execute(
            "INSERT INTO signals "
            "(source, kind, title, detail, ts, meta_json, hash_key, collected_at) "
            "VALUES ('calendar','event','old','','2026-01-01T00:00:00Z','{}','x','now')"
        )
        # Stale briefs table (old schema) — must be dropped by ensure_schema.
        await conn.execute(
            """
            CREATE TABLE briefs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_set_hash TEXT NOT NULL UNIQUE,
                payload_json    TEXT NOT NULL,
                generated_at    TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            "INSERT INTO briefs (signal_set_hash, payload_json, generated_at) "
            "VALUES ('old', '{}', 'now')"
        )
        await conn.commit()

        await ensure_schema(conn)  # upgrade in place

        cur = await conn.execute("PRAGMA table_info(signals)")
        cols = {r[1] for r in await cur.fetchall()}
        assert "project_id" in cols

        # Existing row preserved, project_id NULL.
        cur = await conn.execute("SELECT title, project_id FROM signals")
        rows = await cur.fetchall()
        assert rows == [("old", None)]

        # Stale briefs table must have been dropped.
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='briefs'"
        )
        assert await cur.fetchone() is None


@pytest.mark.asyncio
async def test_task_has_reminder_uuid_column(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(task)")
        cols = {r[1] for r in await cur.fetchall()}
    assert "reminder_uuid" in cols


@pytest.mark.asyncio
async def test_project_has_reminder_calendar_id_column(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(project)")
        cols = {r[1] for r in await cur.fetchall()}
    assert "reminder_calendar_id" in cols


@pytest.mark.asyncio
async def test_reminder_columns_migration_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    async with aiosqlite.connect(db) as conn:
        await ensure_schema(conn)
        await ensure_schema(conn)
        await ensure_schema(conn)
        cur = await conn.execute("PRAGMA table_info(task)")
        task_cols = {r[1] for r in await cur.fetchall()}
        cur = await conn.execute("PRAGMA table_info(project)")
        proj_cols = {r[1] for r in await cur.fetchall()}
    assert "reminder_uuid" in task_cols
    assert "reminder_calendar_id" in proj_cols
