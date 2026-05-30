"""Settings router — read/write the .env file for API keys.

Only the keys the UI exposes are allowed. Values are written to the .env file
on disk; the process does NOT hot-reload (the user restarts Irma to apply new
keys). The GET endpoint reveals whether a key is set but never its value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from irma_api.config import secret_value_or_none

router = APIRouter(prefix="/settings", tags=["settings"])

# The .env lives two levels above this file:
#   src/irma_api/routers/settings.py  →  ../../  →  services/api/
_ENV_PATH = Path(__file__).parent.parent.parent.parent / ".env"

# Allowed keys — exactly what the UI exposes. Nothing else can be written.
ALLOWED_KEYS: frozenset[str] = frozenset(
    [
        "ANTHROPIC_API_KEY",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
        "RESEND_API_KEY",
        "IRMA_USER_EMAIL",
    ]
)


class KeyStatus(BaseModel):
    key: str
    set: bool


class SettingsStatusResponse(BaseModel):
    keys: list[KeyStatus]
    restart_required: bool  # always True after a POST


class SaveKeysRequest(BaseModel):
    """Map of key → value. Empty-string value clears the key."""

    keys: dict[str, str]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_env() -> dict[str, str]:
    """Parse .env into a plain dict (comments and blank lines stripped)."""
    env: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return env
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    """Write dict back to .env preserving comments from the existing file."""
    existing_lines: list[str] = []
    written_keys: set[str] = set()

    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                existing_lines.append(line)
                continue
            if "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in env:
                    # Rewrite the line with the new value.
                    existing_lines.append(f"{k}={env[k]}")
                    written_keys.add(k)
                else:
                    existing_lines.append(line)
            else:
                existing_lines.append(line)

    # Append any new keys that weren't already in the file.
    for k, v in env.items():
        if k not in written_keys:
            existing_lines.append(f"{k}={v}")

    _ENV_PATH.write_text("\n".join(existing_lines) + "\n")


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=SettingsStatusResponse)
async def get_settings_status(request: Request) -> SettingsStatusResponse:
    """Return which keys are currently set (never the values themselves)."""
    settings = request.app.state.settings
    statuses: list[KeyStatus] = []

    for key in sorted(ALLOWED_KEYS):
        attr = key.lower()
        val = getattr(settings, attr, None)
        # SecretStr vs plain str
        is_set = (
            secret_value_or_none(val) is not None
            if hasattr(val, "get_secret_value")
            else bool(val)
        )
        statuses.append(KeyStatus(key=key, set=is_set))

    return SettingsStatusResponse(keys=statuses, restart_required=False)


@router.post("", response_model=SettingsStatusResponse)
async def save_settings(body: SaveKeysRequest) -> SettingsStatusResponse:
    """Write allowed keys to .env. Restart required for changes to take effect."""
    disallowed = set(body.keys) - ALLOWED_KEYS
    if disallowed:
        raise HTTPException(
            status_code=400,
            detail=f"Keys not allowed: {', '.join(sorted(disallowed))}",
        )

    env = _read_env()
    for k, v in body.keys.items():
        if v:
            env[k] = v
        else:
            env.pop(k, None)

    _write_env(env)

    # Reflect the updated on-disk state in the response (process still has old
    # values — restart needed).
    statuses: list[KeyStatus] = []
    for key in sorted(ALLOWED_KEYS):
        statuses.append(KeyStatus(key=key, set=bool(env.get(key))))

    return SettingsStatusResponse(keys=statuses, restart_required=True)
