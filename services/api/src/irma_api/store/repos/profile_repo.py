"""Async access for the single-row `profile` table.

The profile row is self-seeding: callers never need to handle a missing row.
`ensure_seeded` inserts defaults on first access; `get` calls it implicitly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from irma_api.models.profile import Profile, ProfileUpdate

_COLUMNS = (
    "id, owner_name, owner_role, owner_email, timezone, persona_blurb, "
    "calendar_exclude_ids, daily_brief_enabled, brief_hour, "
    "brief_lookahead_days, setup_complete, updated_at"
)

_DEFAULT_UPDATED_AT = "1970-01-01T00:00:00+00:00"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _row_to_profile(row: aiosqlite.Row) -> Profile:
    return Profile(
        id=row["id"],
        owner_name=row["owner_name"],
        owner_role=row["owner_role"],
        owner_email=row["owner_email"],
        timezone=row["timezone"],
        persona_blurb=row["persona_blurb"],
        calendar_exclude_ids=json.loads(row["calendar_exclude_ids"]),
        daily_brief_enabled=bool(row["daily_brief_enabled"]),
        brief_hour=row["brief_hour"],
        brief_lookahead_days=row["brief_lookahead_days"],
        setup_complete=bool(row["setup_complete"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class ProfileRepo:
    """Pure data access for the singleton `profile` row. No business logic."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_seeded(self) -> Profile:
        """Insert the default row if absent, then return the current profile."""
        await self._conn.execute(
            f"""
            INSERT OR IGNORE INTO profile ({_COLUMNS})
            VALUES (1, 'there', '', NULL, 'UTC', '', '[]', 1, 8, 3, 0, ?)
            """,
            (_DEFAULT_UPDATED_AT,),
        )
        await self._conn.commit()
        return await self.get()

    async def get(self) -> Profile:
        """Return the profile row, seeding defaults on first call."""
        cur = await self._conn.execute(
            f"SELECT {_COLUMNS} FROM profile WHERE id = 1"
        )
        row = await cur.fetchone()
        if row is None:
            return await self.ensure_seeded()
        return _row_to_profile(row)

    async def update(self, patch: ProfileUpdate) -> Profile:
        """Apply only the fields present in *patch*, bump updated_at, return refreshed row."""
        updates: dict[str, Any] = patch.model_dump(exclude_unset=True)
        if not updates:
            return await self.get()

        # Ensure the row exists before we try to UPDATE it.
        await self.ensure_seeded()

        sets: list[str] = []
        params: list[object] = []
        for key, value in updates.items():
            if key == "calendar_exclude_ids":
                sets.append("calendar_exclude_ids = ?")
                params.append(json.dumps(value))
            elif key in ("daily_brief_enabled", "setup_complete"):
                sets.append(f"{key} = ?")
                params.append(1 if value else 0)
            else:
                sets.append(f"{key} = ?")
                params.append(value)

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        # WHERE clause: always the singleton row
        params.append(1)

        await self._conn.execute(
            f"UPDATE profile SET {', '.join(sets)} WHERE id = ?", params
        )
        await self._conn.commit()
        return await self.get()
