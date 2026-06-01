"""One-time .env → profile import for existing single-user installs.

Running `import_env_defaults` at startup populates the profile table from
legacy Settings values so users who have a `.env` but have never opened the
setup wizard still get a fully-seeded profile — and are marked
`setup_complete=True` so the wizard never interrupts them.

Rules:
- If `setup_complete` is already True, the function returns immediately
  (idempotent — the user has already configured their profile).
- Only writes to fields that still hold their neutral default values; it
  never clobbers anything the user intentionally set.
"""

from __future__ import annotations

from irma_api.config import Settings
from irma_api.models.profile import ProfileUpdate
from irma_api.store.repos.profile_repo import ProfileRepo


async def import_env_defaults(repo: ProfileRepo, settings: Settings) -> None:
    """Copy legacy `.env` values into the profile row on first boot.

    Args:
        repo: An already-connected :class:`ProfileRepo`.
        settings: The process-wide :class:`Settings` singleton.
    """
    profile = await repo.ensure_seeded()

    if profile.setup_complete:
        # Already migrated or manually configured — nothing to do.
        return

    patch_kwargs: dict[str, object] = {}

    # owner_email ── import if profile still has the null default
    if profile.owner_email is None and settings.irma_user_email:
        patch_kwargs["owner_email"] = settings.irma_user_email

    # timezone ── import if profile is still on the "UTC" neutral default
    if profile.timezone == "UTC" and settings.irma_brief_timezone != "UTC":
        patch_kwargs["timezone"] = settings.irma_brief_timezone

    # brief_hour ── import if profile is still on 8 and setting differs
    if profile.brief_hour == 8 and settings.irma_brief_hour != 8:
        patch_kwargs["brief_hour"] = settings.irma_brief_hour

    # calendar_exclude_ids ── import if profile list is empty and setting is non-empty
    if not profile.calendar_exclude_ids and settings.irma_calendar_exclude_ids:
        patch_kwargs["calendar_exclude_ids"] = list(settings.irma_calendar_exclude_ids)

    # brief_lookahead_days ── import only if still on the neutral default (3) and env differs
    if profile.brief_lookahead_days == 3 and settings.irma_brief_lookahead_days != 3:
        patch_kwargs["brief_lookahead_days"] = settings.irma_brief_lookahead_days

    # daily_brief_enabled ── import only if profile is still True (default) and env disables it
    if profile.daily_brief_enabled and not settings.irma_daily_brief_enabled:
        patch_kwargs["daily_brief_enabled"] = settings.irma_daily_brief_enabled

    # Mark existing owners as already set up so they never see the wizard.
    if settings.irma_user_email:
        patch_kwargs["setup_complete"] = True

    if patch_kwargs:
        await repo.update(ProfileUpdate(**patch_kwargs))
