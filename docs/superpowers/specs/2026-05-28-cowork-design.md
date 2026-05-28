# feat/cowork — Claude subscription as a chat backend

**Status:** approved (Amit, 2026-05-28). Implementation proceeds without separate plan.
**Branch:** `feat/cowork`, based on `feat/resend-and-calendar` (depends on `7f99ed5` tool-use surface and `890da01` /chat tool-call loop).

## Problem

Irma's `/chat` currently supports two backends — Anthropic API (token-billed) and Ollama (local). The maintainer pays for a Claude Code subscription that is *not* utilized by Irma. Goal: add a third backend that drives chat through the `claude` CLI subprocess, leveraging the existing subscription auth without sending API-token traffic. The companion chat UI gets a per-conversation backend toggle.

## Non-goals

- Streaming token-by-token output (current chat is single-shot reply).
- Tool use via the Claude backend (Irma's `send_email` / task tools won't be reachable when the `claude_cli` backend is selected). The other backends keep tools.
- Surfacing a visible terminal window with `claude` running (deferred; the proxy is the primary surface).
- Driving `LeadAgent` standup synthesis through `claude_cli`. Synthesis stays on whatever `IRMA_LLM_BACKEND` selects.

## Architecture

```
ChatView.tsx ──┐                          ┌── ClaudeCliLLM ── claude -p --session-id <uuid>
   (backend +  │  POST /api/v1/chat       │      (per-turn subprocess; new)
   session_id  ├─>  { messages, backend,  │
   from UI)    │     session_id }     ────┼── AnthropicLLM   (unchanged)
               │                          │
               │                          └── OllamaLLM      (unchanged)
                                         registry: dict[str, LLMClient]
                                         keyed by backend name, built at startup
```

`build_llm_client(settings)` → `LLMClient | None` is replaced by `build_llm_registry(settings)` → `dict[str, LLMClient]`. Every backend that can be built from current settings is registered. The chat router picks a client per request; `LeadAgent` continues to read `settings.irma_llm_backend` and looks up the default in the same registry.

## `ClaudeCliLLM` contract

```python
class ClaudeCliLLM:
    backend = "claude_cli"

    def __init__(
        self,
        *,
        binary: str = "claude",
        model: str | None = None,        # None → user's claude default
        cwd: Path | None = None,         # defaults to project root
        timeout_seconds: float = 90.0,
    ) -> None: ...

    async def complete(
        self,
        *,
        system: str,
        messages: list[ChatTurn],
        tools: list[ToolSpec] | None = None,    # ignored (warns once if non-empty)
        max_tokens: int = 1500,                  # ignored (CLI has no equivalent)
        session_id: str,                         # NEW kwarg, UUID; required for claude_cli
    ) -> CompleteResult: ...
```

Wire call per turn:

```
claude -p
  --session-id <uuid>
  --system-prompt <IRMA_PERSONA>
  --model <model>              # only if configured
  --disallowedTools "*"
  --disable-slash-commands
  --output-format json
  --permission-mode default
  <last user message text>
```

- Only the latest user `ChatTurn.content` is passed as the prompt arg. Earlier turns are reconstructed by Claude from its session file on disk, addressed by the same UUID across turns.
- `--output-format json` returns one envelope; `result` carries the assistant text. We return `TextResult(text=result.strip())`.
- `is_error: true` → raise `RuntimeError(f"claude {subtype}: {message}")`; chat router maps to 502.

### `LLMClient` protocol change

The `complete()` method gains `session_id: str | None = None`. `AnthropicLLM` and `OllamaLLM` accept and ignore it. `ClaudeCliLLM` requires it (raises `ValueError` if None or not a valid UUID).

### Auth & failure modes

- `claude` not on PATH → `FileNotFoundError` caught at registry build time → backend simply absent from the registry.
- Non-zero exit + stderr → `RuntimeError("claude exited N: <last 500 chars of stderr>")`.
- Timeout (90s default) → kill process group, raise `TimeoutError`.
- Auth missing → JSON envelope sets `result_type == "error"` with an auth-related subtype; we raise `RuntimeError("claude not authenticated — run `claude /login` once")`.

## Backend selection UX

`ChatView.tsx` gets a small segmented control above the input:

```
Backend:  [ Local ]  [ Claude ]  [ API ]                 (only shows backends the server registered)
```

- Selection is persisted in `localStorage["irma.chat.backend"]`. Default = whatever the server's default is on first paint (fetched once from `GET /api/v1/chat/backends` — see API).
- A `session_id = crypto.randomUUID()` is held in component state and minted fresh whenever the conversation is cleared (or on first message of an empty chat). Not stored in localStorage — closing/reopening the window starts a fresh Claude session, matching how the rest of the chat history isn't persisted either.

## API changes

| Method | Path | Change |
|---|---|---|
| GET | `/api/v1/chat/backends` | **new.** Returns `{ default: str, available: [str], models: { backend: model_str } }` so the UI knows which buttons to render. |
| POST | `/api/v1/chat` | Request body gains `backend: str \| None` and `session_id: str \| None`. If `backend` is unknown, 400. If `backend == "claude_cli"`, `session_id` is required (UUID format), 400 otherwise. If `backend` is omitted, the server default is used. |

`ChatResponse` already returns `backend` and `model`; for `claude_cli` we return the actual model from the JSON envelope's `modelUsage` key (e.g. `claude-opus-4-7`).

## Tool-use stance

`claude_cli` is text-only in v1. The chat router currently runs a tool-call loop (`/chat` tool-call loop, commit `890da01`). When `backend == "claude_cli"`, the router skips the tool loop entirely — Irma's tools aren't passed in, and the reply text is returned as-is. This is the documented trade-off of using the subscription path; users who want `send_email` etc. pick the API or Ollama backend.

## Config additions

`services/api/src/irma_api/config.py`:

```python
LLMBackend = Literal["anthropic", "ollama", "claude_cli"]

# new fields
claude_cli_binary: str = "claude"
claude_cli_model: str | None = None       # None → user's claude default
claude_cli_timeout_seconds: float = 90.0
```

`.env.example` documents the new keys.

## Testing

`services/api/tests/test_llm_claude_cli.py` (new):
- `complete()` builds the correct argv (asserts flag order, session-id, system-prompt, model omission).
- Success: mock `asyncio.create_subprocess_exec` to inject a stdout JSON envelope; assert `TextResult(text=...)`.
- Error envelope (`is_error: true`): assert `RuntimeError`.
- Timeout: assert `TimeoutError` after killing the mock process.
- Missing `session_id`: `ValueError`.

`services/api/tests/test_chat_tool_loop.py` (extended) and/or `test_chat_backend_dispatch.py`:
- Request with `backend="claude_cli"` and no `session_id` → 400.
- Request with `backend="claude_cli"` + UUID → router dispatches to the right registry entry (mock the registry).
- `GET /api/v1/chat/backends` shape.

Manual verification (must run before reporting done):
1. `cd services/api && uv run uvicorn irma_api.app:app --reload`.
2. `pnpm tauri dev` (or `pnpm dev` if just the web UI is fine).
3. Open chat, pick "Claude", send "say hi"; verify reply renders and `meta` shows `claude_cli · claude-opus-4-7`.
4. Send a follow-up referencing the prior turn; verify Claude remembers (session continuity works).
5. Pick "Local", verify it falls back cleanly.

## Files touched

Backend:
- `services/api/src/irma_api/agents/llm.py` — `ClaudeCliLLM`, `build_llm_registry`, protocol signature gains `session_id`.
- `services/api/src/irma_api/config.py` — `LLMBackend` literal + 3 new fields.
- `services/api/src/irma_api/app.py` — attach `llm_registry` + a `default_backend` string.
- `services/api/src/irma_api/routers/chat.py` — accept `backend` and `session_id`, dispatch via registry, `GET /chat/backends` endpoint, skip tool loop when `claude_cli`.
- `services/api/.env.example` — new keys.

Frontend:
- `apps/desktop/src/lib/types.ts` — extend `ChatRequest` types.
- `apps/desktop/src/lib/api.ts` — `sendChat(messages, opts?)`, `getChatBackends()`.
- `apps/desktop/src/main/chat/ChatView.tsx` — segmented control, sessionId state, localStorage persistence.

Tests:
- `services/api/tests/test_llm_claude_cli.py` (new).
- `services/api/tests/test_chat_tool_loop.py` (extended) — backend dispatch + 400 cases.

## Risks & open questions

- **First-turn cold start (~2s).** Tolerable for chat. Not tolerable if we later want to drive synthesis through this path — punt that decision.
- **Session files accumulate under `~/.claude/`.** No active GC. Acceptable; user can clear via `claude` directly.
- **Concurrent turns on the same session.** UI is single-message-at-a-time (`busy` flag), so we don't need a lock. Document it.
- **`disallowedTools "*"` syntax.** Verified empirically against `claude --version 2.1.153`; if a future version changes the wildcard semantics, the tests covering argv construction catch it.

## Deferred / Phase-2 ideas

- Visible terminal pane showing `claude --resume <session_id>` so the user can take over interactively. Requires a small Tauri command to spawn Terminal.app.
- Long-lived `claude --input-format stream-json --output-format stream-json` subprocess per chat — true streaming, native tool_use blocks, would unlock Irma-tools-through-Claude.
- Drive `LeadAgent` synthesis through `claude_cli` to avoid token billing on the daily standup brief.
