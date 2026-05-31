from __future__ import annotations

from pathlib import Path

from irma_api.config import Settings


def test_reminders_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.reminders_linked is False
    assert s.reminders_calendar_prefix == "Irma · "
    assert s.reminders_sync_interval_seconds == 60
    assert isinstance(s.reminders_helper_path, Path)
    assert s.reminders_helper_path.name == "irma-reminders-helper"


def test_reminders_linked_from_env(monkeypatch) -> None:
    monkeypatch.setenv("REMINDERS_LINKED", "true")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.reminders_linked is True
