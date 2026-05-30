from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from irma_api.integrations.reminders.bridge import BridgeError, ReminderBridge
from irma_api.integrations.reminders.models import BatchOp, ReminderFields

FAKE = Path(__file__).parent / "fixtures" / "fake_helper.py"


@pytest.fixture
def bridge(tmp_path: Path) -> ReminderBridge:
    state_file = tmp_path / "state.json"
    return ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(FAKE),),
        env={"FAKE_HELPER_STATE": str(state_file)},
    )


@pytest.mark.asyncio
async def test_access_status_returns_authorized(bridge: ReminderBridge) -> None:
    assert (await bridge.access_status()) == "authorized"


@pytest.mark.asyncio
async def test_request_access_grants(bridge: ReminderBridge) -> None:
    granted = await bridge.request_access()
    assert granted is True


@pytest.mark.asyncio
async def test_ensure_list_is_stable(bridge: ReminderBridge) -> None:
    a = await bridge.ensure_list("Irma · Alpha")
    b = await bridge.ensure_list("Irma · Alpha")
    assert a == b


@pytest.mark.asyncio
async def test_list_calendars_filters_by_prefix(bridge: ReminderBridge) -> None:
    await bridge.ensure_list("Irma · Alpha")
    await bridge.ensure_list("Irma · Beta")
    await bridge.ensure_list("Other List")  # outside the prefix
    cals = await bridge.list_calendars("Irma · ")
    titles = sorted(c.title for c in cals)
    assert titles == ["Irma · Alpha", "Irma · Beta"]


@pytest.mark.asyncio
async def test_rename_calendar_updates_title(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma · Alpha")
    changed = await bridge.rename_calendar(cal_id, "Irma · Renamed")
    assert changed is True
    cals = await bridge.list_calendars("Irma · ")
    assert [c.title for c in cals] == ["Irma · Renamed"]


@pytest.mark.asyncio
async def test_rename_calendar_no_op_when_title_matches(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma · Alpha")
    changed = await bridge.rename_calendar(cal_id, "Irma · Alpha")
    assert changed is False


@pytest.mark.asyncio
async def test_list_empty(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma · Alpha")
    rems = await bridge.list(cal_id)
    assert rems == []


@pytest.mark.asyncio
async def test_batch_create_then_list(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma · Alpha")
    results = await bridge.batch(
        cal_id,
        [BatchOp.create_op(ReminderFields(title="x", due_date=date(2026, 6, 1)))],
        continue_on_error=False,
    )
    assert len(results) == 1
    assert results[0].ok
    rems = await bridge.list(cal_id)
    assert len(rems) == 1
    assert rems[0].title == "x"
    assert rems[0].due_date == date(2026, 6, 1)


@pytest.mark.asyncio
async def test_delete_calendar(bridge: ReminderBridge) -> None:
    cal_id = await bridge.ensure_list("Irma · Throwaway")
    deleted = await bridge.delete_calendar(cal_id)
    assert deleted is True
    cals = await bridge.list_calendars("Irma · ")
    assert all(c.calendar_id != cal_id for c in cals)


@pytest.mark.asyncio
async def test_bridge_error_on_unknown_command(tmp_path: Path) -> None:
    bridge = ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(FAKE),),
        env={"FAKE_HELPER_STATE": str(tmp_path / "s.json")},
    )
    with pytest.raises(BridgeError) as exc:
        await bridge._invoke(["bogus"], stdin=b"")
    assert "unknown_command" in str(exc.value)


@pytest.mark.asyncio
async def test_bridge_error_on_non_json(tmp_path: Path) -> None:
    """A binary that exits 0 but emits garbage on stdout must surface as BridgeError."""
    bad_helper = tmp_path / "bad_helper.py"
    bad_helper.write_text("import sys; print('not json'); sys.exit(0)\n")
    bridge = ReminderBridge(
        binary_path=Path(sys.executable),
        binary_argv_prefix=(str(bad_helper),),
        env={},
    )
    with pytest.raises(BridgeError):
        await bridge.access_status()
