"""Runtime configuration loaded from environment + ``.env``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LLMBackend = Literal["anthropic", "ollama", "claude_cli"]


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

    # --- LLM backend ---------------------------------------------------------
    # Which provider powers LeadAgent synthesis + /chat. Switch to "ollama" to
    # run fully offline against a local model (qwen2.5:7b by default).
    irma_llm_backend: LLMBackend = "anthropic"

    # --- Claude --------------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-6"

    # --- Ollama --------------------------------------------------------------
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"

    # --- Claude CLI (subscription-backed) ------------------------------------
    # Shells out to the `claude` binary for chat replies so we ride the user's
    # Claude Code subscription instead of billing API tokens. No API key needed
    # — claude authenticates via its own keychain/OAuth.
    claude_cli_binary: str = "claude"
    claude_cli_model: str | None = None
    claude_cli_timeout_seconds: float = 90.0

    # --- Google Calendar -----------------------------------------------------
    google_oauth_client_id: SecretStr | None = None
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_refresh_token: SecretStr | None = None

    # --- Identity ------------------------------------------------------------
    # Recipient lock for the send_email tool. Required when the Resend tool is
    # enabled; if unset, the tool refuses to register at startup and chat
    # continues without it.
    irma_user_email: str | None = None

    # --- Resend (send_email tool) -------------------------------------------
    # The LLM-callable `send_email` tool routes through Resend's REST API.
    # Without a key the tool is not registered and chat still works.
    resend_api_key: SecretStr | None = None
    resend_from_email: str = "onboarding@resend.dev"

    # --- Observers -----------------------------------------------------------
    # NoDecode → pydantic-settings hands us the raw env string (comma-separated
    # paths) instead of trying to JSON-decode the list.
    irma_repos: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    irma_codebase_agent_enabled: bool = False
    irma_refresh_minutes: int = 30
    irma_dock_clearance: float = 80.0
    irma_db_path: Path = Path("./irma.db")

    # --- HTTP ----------------------------------------------------------------
    irma_api_host: str = "127.0.0.1"
    irma_api_port: int = 8765

    @field_validator("irma_repos", mode="before")
    @classmethod
    def _split_repos(cls, raw: object) -> object:
        """Accept ``IRMA_REPOS=/a,/b,/c`` from .env in addition to a JSON list."""
        if isinstance(raw, str):
            paths = [p.strip() for p in raw.split(",") if p.strip()]
            return [Path(p) for p in paths]
        return raw


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
