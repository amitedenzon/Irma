#!/usr/bin/env python3
"""Python implementation of the Swift helper's JSON surface for tests.

State is loaded from / saved to a JSON file pointed to by
$FAKE_HELPER_STATE so successive invocations in the same test see the
same in-memory store.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_path() -> Path:
    raw = os.environ.get("FAKE_HELPER_STATE")
    if not raw:
        print(
            json.dumps({"error": "no_state", "message": "FAKE_HELPER_STATE unset"}),
            file=sys.stderr,
        )
        sys.exit(2)
    return Path(raw)


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {
            "access": "authorized",
            "grant": True,
            "lists": {},        # title -> calendar_id
            "store": {},        # calendar_id -> {uuid -> reminder}
            "counter": 0,
        }
    return json.loads(path.read_text())


def _save(state: dict[str, Any]) -> None:
    _state_path().write_text(json.dumps(state))


def _next_uuid(state: dict[str, Any]) -> str:
    state["counter"] += 1
    return f"R-{state['counter']}"


def _next_cal_id(state: dict[str, Any]) -> str:
    state["counter"] += 1
    return f"CAL-{state['counter']}"


def _ok(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def _err(code: str, message: str) -> None:
    print(json.dumps({"error": code, "message": message}), file=sys.stderr)
    sys.exit(2)


def cmd_access_status(state: dict[str, Any]) -> None:
    _ok({"status": state["access"]})


def cmd_request_access(state: dict[str, Any]) -> None:
    granted = bool(state.get("grant", True))
    state["access"] = "authorized" if granted else "denied"
    _save(state)
    if granted:
        _ok({"granted": True})
    else:
        _ok({"granted": False, "reason": "denied"})


def cmd_ensure_list(state: dict[str, Any], name: str) -> None:
    if name in state["lists"]:
        _ok({"calendar_id": state["lists"][name]})
        return
    cal_id = _next_cal_id(state)
    state["lists"][name] = cal_id
    state["store"].setdefault(cal_id, {})
    _save(state)
    _ok({"calendar_id": cal_id})


def cmd_list_calendars(state: dict[str, Any], prefix: str) -> None:
    out = [
        {"calendar_id": cid, "title": title}
        for title, cid in state["lists"].items()
        if title.startswith(prefix)
    ]
    out.sort(key=lambda c: c["title"])
    _ok({"calendars": out})


def cmd_rename_calendar(state: dict[str, Any], cal_id: str, new_title: str) -> None:
    old_title = next((t for t, cid in state["lists"].items() if cid == cal_id), None)
    if old_title is None:
        _err("calendar_not_found", cal_id)
        return
    if old_title == new_title:
        _ok({"renamed": False})
        return
    del state["lists"][old_title]
    state["lists"][new_title] = cal_id
    _save(state)
    _ok({"renamed": True})


def cmd_list(state: dict[str, Any], cal_id: str) -> None:
    rems = state["store"].get(cal_id)
    if rems is None:
        _err("calendar_not_found", cal_id)
        return
    out = sorted(rems.values(), key=lambda r: r["uuid"])
    _ok({"reminders": out})


def _apply_create(state: dict[str, Any], cal_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    uuid = _next_uuid(state)
    rem = {
        "uuid": uuid,
        "title": fields.get("title") or "",
        "notes": fields.get("notes") or "",
        "due_date": fields.get("due_date"),
        "start_date": fields.get("start_date"),
        "is_completed": bool(fields.get("is_completed") or False),
        "completion_date": now if fields.get("is_completed") else None,
        "last_modified": now,
    }
    state["store"][cal_id][uuid] = rem
    return {"index": -1, "ok": True, "uuid": uuid, "last_modified": now}


def _apply_update(
    state: dict[str, Any], cal_id: str, uuid: str, fields: dict[str, Any]
) -> dict[str, Any]:
    cur = state["store"][cal_id].get(uuid)
    if cur is None:
        raise KeyError(uuid)
    now = _now()
    for key in ("title", "notes", "due_date", "start_date"):
        if key in fields and fields[key] is not None:
            cur[key] = fields[key]
    if "is_completed" in fields and fields["is_completed"] is not None:
        cur["is_completed"] = bool(fields["is_completed"])
        cur["completion_date"] = now if cur["is_completed"] else None
    cur["last_modified"] = now
    return {"index": -1, "ok": True, "uuid": uuid, "last_modified": now}


def _apply_delete(state: dict[str, Any], cal_id: str, uuid: str) -> dict[str, Any]:
    if uuid not in state["store"][cal_id]:
        raise KeyError(uuid)
    del state["store"][cal_id][uuid]
    return {"index": -1, "ok": True, "uuid": uuid}


def cmd_batch(state: dict[str, Any], cal_id: str, continue_on_error: bool) -> None:
    if cal_id not in state["store"]:
        _err("calendar_not_found", cal_id)
        return
    input_data = json.loads(sys.stdin.read() or "{}")
    ops = input_data.get("ops", [])
    results: list[dict[str, Any]] = []
    for idx, op in enumerate(ops):
        try:
            if op["op"] == "create":
                r = _apply_create(state, cal_id, op["fields"])
            elif op["op"] == "update":
                r = _apply_update(state, cal_id, op["uuid"], op["fields"])
            elif op["op"] == "delete":
                r = _apply_delete(state, cal_id, op["uuid"])
            else:
                raise ValueError(f"bad op {op['op']!r}")
            r["index"] = idx
            results.append(r)
        except Exception as exc:
            results.append({"index": idx, "ok": False, "error": str(exc)})
            if not continue_on_error:
                break
    _save(state)
    _ok({"results": results})


def cmd_delete_calendar(state: dict[str, Any], cal_id: str) -> None:
    deleted = state["store"].pop(cal_id, None) is not None
    state["lists"] = {k: v for k, v in state["lists"].items() if v != cal_id}
    _save(state)
    _ok({"deleted": deleted})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("--name", default=None)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--calendar-id", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()

    state = _load()
    cmd = args.command
    if cmd == "access-status":
        cmd_access_status(state)
    elif cmd == "request-access":
        cmd_request_access(state)
    elif cmd == "ensure-list":
        assert args.name, "--name required"
        cmd_ensure_list(state, args.name)
    elif cmd == "list-calendars":
        assert args.prefix is not None, "--prefix required"
        cmd_list_calendars(state, args.prefix)
    elif cmd == "rename-calendar":
        assert args.calendar_id, "--calendar-id required"
        assert args.title is not None, "--title required"
        cmd_rename_calendar(state, args.calendar_id, args.title)
    elif cmd == "list":
        assert args.calendar_id, "--calendar-id required"
        cmd_list(state, args.calendar_id)
    elif cmd == "batch":
        assert args.calendar_id, "--calendar-id required"
        cmd_batch(state, args.calendar_id, args.continue_on_error)
    elif cmd == "delete-calendar":
        assert args.calendar_id, "--calendar-id required"
        cmd_delete_calendar(state, args.calendar_id)
    else:
        _err("unknown_command", cmd)


if __name__ == "__main__":
    main()
