"""ClaudeCliLLM — argv construction, JSON envelope parsing, error paths.

The CLI is mocked via ``asyncio.create_subprocess_exec``; nothing executes
``claude`` for real. We focus on:
  * the exact argv the subprocess sees,
  * happy-path JSON envelope → ``TextResult`` translation,
  * envelope-level error (``is_error: true``) → ``RuntimeError`` or
    ``ClaudeAuthError`` depending on subtype/detail,
  * non-zero exit code → ``RuntimeError`` carrying stderr tail,
  * timeout → ``TimeoutError`` after killing the process.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from irma_api.agents.llm import (
    ChatTurn,
    ClaudeAuthError,
    ClaudeCliLLM,
    TextResult,
)

_VALID_UUID = "11111111-2222-3333-4444-555555555555"


class _FakeProcess:
    """Minimal stand-in for ``asyncio.subprocess.Process``."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        communicate_delay: float = 0.0,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode: int | None = returncode
        self._delay = communicate_delay
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode or 0


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch, proc: _FakeProcess
) -> dict[str, Any]:
    """Replace asyncio.create_subprocess_exec, capture argv + kwargs."""
    captured: dict[str, Any] = {}

    async def fake_exec(*argv: str, **kwargs: Any) -> _FakeProcess:
        captured["argv"] = list(argv)
        captured["kwargs"] = kwargs
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return captured


def _envelope(
    *,
    result: str = "PONG",
    is_error: bool = False,
    subtype: str = "success",
    model: str = "claude-opus-4-7",
) -> bytes:
    return json.dumps(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "result": result,
            "modelUsage": {model: {"inputTokens": 1, "outputTokens": 1}},
        }
    ).encode()


@pytest.mark.asyncio
async def test_complete_returns_text_and_updates_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(stdout=_envelope(result="hi there", model="claude-opus-4-7[1m]"))
    captured = _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()
    out = await llm.complete(
        system="persona",
        messages=[ChatTurn(role="user", content="hello")],
        session_id=_VALID_UUID,
    )
    assert isinstance(out, TextResult)
    assert out.text == "hi there"
    assert llm.model == "claude-opus-4-7[1m]"
    assert captured["argv"][0] == "claude"
    assert "-p" in captured["argv"]


@pytest.mark.asyncio
async def test_argv_contains_required_flags_and_omits_model_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(stdout=_envelope())
    captured = _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()  # no model configured
    await llm.complete(
        system="PERSONA",
        messages=[ChatTurn(role="user", content="hi")],
        session_id=_VALID_UUID,
    )
    argv = captured["argv"]
    assert "--session-id" in argv
    assert argv[argv.index("--session-id") + 1] == _VALID_UUID
    assert "--system-prompt" in argv
    assert argv[argv.index("--system-prompt") + 1] == "PERSONA"
    assert "--disallowedTools" in argv
    assert argv[argv.index("--disallowedTools") + 1] == "*"
    assert "--disable-slash-commands" in argv
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert "--model" not in argv  # model not configured → flag omitted
    assert argv[-1] == "hi"  # last positional is the user message


@pytest.mark.asyncio
async def test_argv_includes_model_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(stdout=_envelope())
    captured = _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM(model="sonnet")
    await llm.complete(
        system="x",
        messages=[ChatTurn(role="user", content="msg")],
        session_id=_VALID_UUID,
    )
    argv = captured["argv"]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"


@pytest.mark.asyncio
async def test_only_latest_user_message_passed_as_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(stdout=_envelope())
    captured = _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()
    await llm.complete(
        system="x",
        messages=[
            ChatTurn(role="user", content="first"),
            ChatTurn(role="assistant", content="reply"),
            ChatTurn(role="user", content="latest"),
        ],
        session_id=_VALID_UUID,
    )
    assert captured["argv"][-1] == "latest"


@pytest.mark.asyncio
async def test_missing_session_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, _FakeProcess(stdout=_envelope()))
    llm = ClaudeCliLLM()
    with pytest.raises(ValueError, match="session_id"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=None,
        )


@pytest.mark.asyncio
async def test_non_uuid_session_id_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, _FakeProcess(stdout=_envelope()))
    llm = ClaudeCliLLM()
    with pytest.raises(ValueError, match="UUID"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id="not-a-uuid",
        )


@pytest.mark.asyncio
async def test_no_user_message_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_subprocess(monkeypatch, _FakeProcess(stdout=_envelope()))
    llm = ClaudeCliLLM()
    with pytest.raises(ValueError, match="no user message"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="assistant", content="hi")],
            session_id=_VALID_UUID,
        )


@pytest.mark.asyncio
async def test_error_envelope_raises_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(
        stdout=_envelope(is_error=True, subtype="model_error", result="rate limited"),
    )
    _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()
    with pytest.raises(RuntimeError, match=r"model_error.*rate limited"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=_VALID_UUID,
        )


@pytest.mark.asyncio
async def test_auth_error_envelope_raises_claude_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(
        stdout=_envelope(
            is_error=True, subtype="auth_error", result="please log in"
        ),
    )
    _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()
    with pytest.raises(ClaudeAuthError):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=_VALID_UUID,
        )


@pytest.mark.asyncio
async def test_nonzero_exit_raises_with_stderr_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(stdout=b"", stderr=b"boom!\n" * 200, returncode=2)
    _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()
    with pytest.raises(RuntimeError, match="claude exited 2"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=_VALID_UUID,
        )


@pytest.mark.asyncio
async def test_timeout_kills_process_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(
        stdout=_envelope(), communicate_delay=5.0, returncode=0
    )
    _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM(timeout_seconds=0.05)
    with pytest.raises(TimeoutError):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=_VALID_UUID,
        )
    assert proc.killed is True


@pytest.mark.asyncio
async def test_non_json_stdout_raises_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = _FakeProcess(stdout=b"not json at all")
    _patch_subprocess(monkeypatch, proc)
    llm = ClaudeCliLLM()
    with pytest.raises(RuntimeError, match="non-JSON"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=_VALID_UUID,
        )
