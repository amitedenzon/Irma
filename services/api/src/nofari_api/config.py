"""Runtime configuration loaded from environment + ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Reads from process environment first, then ``.env`` if present. Secrets
    are wrapped in :class:`SecretStr` so they never appear in ``repr()``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Claude --------------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # --- Google Calendar -----------------------------------------------------
    google_oauth_client_id: SecretStr | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_refresh_token: SecretStr | None = None

    # --- Observers -----------------------------------------------------------
    nofari_repos: list[Path] = Field(default_factory=list)
    nofari_refresh_minutes: int = 30
    nofari_dock_clearance: float = 80.0
    nofari_db_path: Path = Path("./nofari.db")

    # --- HTTP ----------------------------------------------------------------
    nofari_api_host: str = "127.0.0.1"
    nofari_api_port: int = 8765

    @field_validator("nofari_repos", mode="before")
    @classmethod
    def _split_repos(cls, raw: object) -> object:
        """Accept ``NOFARI_REPOS=/a,/b,/c`` from .env in addition to a JSON list."""
        if isinstance(raw, str):
            paths = [p.strip() for p in raw.split(",") if p.strip()]
            return [Path(p) for p in paths]
        return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
