from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from irma_api.app import create_app


@pytest.mark.asyncio
async def test_lifespan_exposes_reminder_bridge_when_binary_present(tmp_path, monkeypatch):
    fake_bin = tmp_path / "irma-reminders-helper"
    fake_bin.write_text("#!/bin/sh\necho '{}'\n")
    fake_bin.chmod(0o755)
    monkeypatch.setenv("REMINDERS_HELPER_PATH", str(fake_bin))
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot.db"))
    monkeypatch.chdir(tmp_path)
    from irma_api.config import get_settings
    get_settings.cache_clear()

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t"):
        async with app.router.lifespan_context(app):
            assert hasattr(app.state, "reminder_bridge")
            assert app.state.reminder_bridge is not None
            assert hasattr(app.state, "reminder_sync_factory")
            # Unlinked state by default:
            assert getattr(app.state, "reminder_sync", None) is None


@pytest.mark.asyncio
async def test_lifespan_skips_reminder_bridge_when_binary_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("REMINDERS_HELPER_PATH", str(tmp_path / "absent"))
    monkeypatch.setenv("IRMA_DB_PATH", str(tmp_path / "boot.db"))
    monkeypatch.chdir(tmp_path)
    from irma_api.config import get_settings
    get_settings.cache_clear()
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t"):
        async with app.router.lifespan_context(app):
            assert getattr(app.state, "reminder_bridge", None) is None
