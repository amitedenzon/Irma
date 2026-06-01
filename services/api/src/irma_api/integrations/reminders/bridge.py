"""Async subprocess wrapper around the Swift helper binary.

Every method spawns one short-lived subprocess. Stdin/stdout are JSON.
Non-zero exit, non-JSON stdout, or unparseable error JSON on stderr all
surface as `BridgeError`.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Final, Literal

import structlog

from irma_api.integrations.reminders.models import (
    BatchOp,
    BatchResult,
    CalendarSummary,
    HelperReminder,
)

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS: Final[float] = 30.0


class BridgeError(RuntimeError):
    """Helper binary failed: non-zero exit, non-JSON output, or unknown cmd."""

    def __init__(self, code: str, message: str, *, stderr: str = "") -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.stderr = stderr


class ReminderBridge:
    """Async wrapper over `irma-reminders-helper`."""

    def __init__(
        self,
        *,
        binary_path: Path,
        binary_argv_prefix: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
    ) -> None:
        self._binary = binary_path
        self._prefix = binary_argv_prefix
        self._env = env

    async def _invoke(self, args: list[str], *, stdin: bytes) -> bytes:
        argv = [str(self._binary), *self._prefix, *args]
        env = dict(os.environ)
        if self._env:
            env.update(self._env)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise BridgeError("missing_binary", str(exc)) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin), timeout=_TIMEOUT_SECONDS
            )
        except TimeoutError as exc:
            proc.kill()
            raise BridgeError("timeout", f"{argv[0]} did not return in {_TIMEOUT_SECONDS}s") from exc

        if proc.returncode != 0:
            err_text = stderr.decode("utf-8", errors="replace").strip()
            code, message = "subprocess_failed", err_text
            try:
                payload = json.loads(err_text)
                code = str(payload.get("error", code))
                message = str(payload.get("message", message))
            except (ValueError, AttributeError):
                pass
            raise BridgeError(code, message, stderr=err_text)
        return stdout

    async def _invoke_json(self, args: list[str], *, stdin: bytes = b"") -> dict[str, object]:
        out = await self._invoke(args, stdin=stdin)
        text = out.decode("utf-8", errors="replace").strip()
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise BridgeError("invalid_json", f"helper returned non-JSON: {text!r}") from exc
        if not isinstance(data, dict):
            raise BridgeError("invalid_json", f"helper returned non-object: {text!r}")
        return data

    async def access_status(self) -> Literal["authorized", "denied", "restricted", "notDetermined"]:
        data = await self._invoke_json(["access-status"])
        status = data.get("status")
        if status not in {"authorized", "denied", "restricted", "notDetermined"}:
            raise BridgeError("invalid_json", f"unexpected status {status!r}")
        return status  # type: ignore[return-value]

    async def request_access(self) -> bool:
        data = await self._invoke_json(["request-access"])
        return bool(data.get("granted"))

    async def ensure_list(self, name: str) -> str:
        data = await self._invoke_json(["ensure-list", "--name", name])
        cal_id = data.get("calendar_id")
        if not isinstance(cal_id, str):
            raise BridgeError("invalid_json", "ensure-list missing calendar_id")
        return cal_id

    async def list_calendars(self, prefix: str) -> list[CalendarSummary]:
        data = await self._invoke_json(["list-calendars", "--prefix", prefix])
        raw = data.get("calendars", [])
        if not isinstance(raw, list):
            raise BridgeError("invalid_json", "list-calendars missing calendars")
        return [CalendarSummary.model_validate(c) for c in raw]

    async def rename_calendar(self, calendar_id: str, title: str) -> bool:
        data = await self._invoke_json(
            ["rename-calendar", "--calendar-id", calendar_id, "--title", title]
        )
        return bool(data.get("renamed"))

    async def list(self, calendar_id: str) -> list[HelperReminder]:
        data = await self._invoke_json(["list", "--calendar-id", calendar_id])
        raw = data.get("reminders", [])
        if not isinstance(raw, list):
            raise BridgeError("invalid_json", "list missing reminders")
        return [HelperReminder.model_validate(r) for r in raw]

    async def batch(
        self,
        calendar_id: str,
        ops: list[BatchOp],
        *,
        continue_on_error: bool = True,
    ) -> list[BatchResult]:
        payload = {
            "ops": [op.model_dump(mode="json", by_alias=True, exclude_none=True) for op in ops]
        }
        args = ["batch", "--calendar-id", calendar_id]
        if continue_on_error:
            args.append("--continue-on-error")
        data = await self._invoke_json(args, stdin=json.dumps(payload).encode("utf-8"))
        raw = data.get("results", [])
        if not isinstance(raw, list):
            raise BridgeError("invalid_json", "batch missing results")
        return [BatchResult.model_validate(r) for r in raw]

    async def delete_calendar(self, calendar_id: str) -> bool:
        data = await self._invoke_json(["delete-calendar", "--calendar-id", calendar_id])
        return bool(data.get("deleted"))
