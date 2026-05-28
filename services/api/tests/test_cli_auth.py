"""CLI: `irma-api auth google` flow + .env writer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from irma_api.config import get_settings
from irma_api.main import _write_refresh_token_to_env, run_cli


def test_write_refresh_token_appends_to_empty_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("EXISTING_KEY=foo\n")
    _write_refresh_token_to_env(env, "1//new-token", overwrite=False)
    content = env.read_text()
    assert "EXISTING_KEY=foo" in content
    assert "GOOGLE_OAUTH_REFRESH_TOKEN=1//new-token" in content


def test_write_refresh_token_overwrites_existing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("GOOGLE_OAUTH_REFRESH_TOKEN=old\nOTHER=keep\n")
    _write_refresh_token_to_env(env, "new", overwrite=True)
    content = env.read_text()
    assert "GOOGLE_OAUTH_REFRESH_TOKEN=new" in content
    assert "GOOGLE_OAUTH_REFRESH_TOKEN=old" not in content
    assert "OTHER=keep" in content


def test_write_refresh_token_refuses_without_overwrite(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("GOOGLE_OAUTH_REFRESH_TOKEN=old\n")
    with pytest.raises(SystemExit):
        _write_refresh_token_to_env(env, "new", overwrite=False)


def test_run_cli_auth_google_exits_when_creds_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as exc_info:
        run_cli(["auth", "google"])
    assert exc_info.value.code != 0


def test_run_cli_auth_google_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    get_settings.cache_clear()
    fake_flow = AsyncMock()
    fake_flow.return_value.refresh_token = "1//new-token"
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    with patch("irma_api.main.run_installed_app_flow", new=fake_flow):
        run_cli(["auth", "google"])
    assert "GOOGLE_OAUTH_REFRESH_TOKEN=1//new-token" in (
        tmp_path / ".env"
    ).read_text()
