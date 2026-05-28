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


def _patch_subprocess_seq(
    monkeypatch: pytest.MonkeyPatch, procs: list[_FakeProcess]
) -> list[list[str]]:
    """Same as _patch_subprocess but returns a different process per call.

    Returns a list that will be appended to with the argv of each invocation,
    so tests can assert how the second call differed from the first.
    """
    calls: list[list[str]] = []
    queue = list(procs)

    async def fake_exec(*argv: str, **kwargs: Any) -> _FakeProcess:
        calls.append(list(argv))
        return queue.pop(0)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


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


@pytest.mark.asyncio
async def test_second_turn_uses_resume_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same session_id across two turns → first creates, second resumes.

    Regression test: claude refuses to re-create an existing session UUID
    ("Session ID ... is already in use."), so subsequent turns must switch
    from `--session-id` to `--resume`.
    """
    calls = _patch_subprocess_seq(
        monkeypatch,
        [
            _FakeProcess(stdout=_envelope(result="first")),
            _FakeProcess(stdout=_envelope(result="second")),
        ],
    )
    llm = ClaudeCliLLM()
    await llm.complete(
        system="persona",
        messages=[ChatTurn(role="user", content="turn one")],
        session_id=_VALID_UUID,
    )
    await llm.complete(
        system="persona",
        messages=[ChatTurn(role="user", content="turn two")],
        session_id=_VALID_UUID,
    )
    assert len(calls) == 2
    create_argv, resume_argv = calls
    # First turn: --session-id present, --resume absent, --system-prompt present
    assert "--session-id" in create_argv
    assert "--resume" not in create_argv
    assert "--system-prompt" in create_argv
    # Second turn: --resume present, --session-id absent, --system-prompt absent
    assert "--resume" in resume_argv
    assert resume_argv[resume_argv.index("--resume") + 1] == _VALID_UUID
    assert "--session-id" not in resume_argv
    assert "--system-prompt" not in resume_argv


@pytest.mark.asyncio
async def test_already_in_use_falls_back_to_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server-restart case: first turn after a restart sees a session that
    survived on disk. Initial `--session-id` fails with "already in use";
    we recover by retrying with `--resume`."""
    calls = _patch_subprocess_seq(
        monkeypatch,
        [
            _FakeProcess(
                stderr=b"Error: Session ID xxx is already in use.\n",
                returncode=1,
            ),
            _FakeProcess(stdout=_envelope(result="recovered")),
        ],
    )
    llm = ClaudeCliLLM()
    out = await llm.complete(
        system="persona",
        messages=[ChatTurn(role="user", content="hi")],
        session_id=_VALID_UUID,
    )
    assert isinstance(out, TextResult)
    assert out.text == "recovered"
    assert len(calls) == 2
    # First attempt was a create; recovery used --resume.
    assert "--session-id" in calls[0]
    assert "--resume" in calls[1]


@pytest.mark.asyncio
async def test_other_nonzero_exit_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only "already in use" triggers the resume fallback — other errors
    must bubble up immediately without an extra subprocess invocation."""
    calls = _patch_subprocess_seq(
        monkeypatch,
        [_FakeProcess(stderr=b"some other failure\n", returncode=2)],
    )
    llm = ClaudeCliLLM()
    with pytest.raises(RuntimeError, match="claude exited 2"):
        await llm.complete(
            system="x",
            messages=[ChatTurn(role="user", content="hi")],
            session_id=_VALID_UUID,
        )
    assert len(calls) == 1
