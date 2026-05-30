# Claude Terminal Panel — Design

**Date:** 2026-05-30
**Goal:** Replace the broken "Claude" chat backend with an embedded terminal panel in the Irma desktop window that runs `claude` interactively. Persona via `CLAUDE.md`. Projects/tasks access via Irma's existing REST API (no MCP server). Calendar/mail via Claude's already-authorized `mcp__claude_ai_*` servers.

## Problem

`feat/chat-tools-parity` wired `claude_cli` as a chat backend that shells out to `claude -p`. Two structural problems with that:

1. **`-p` mode strips most of what makes Claude Code useful.** No streaming, no slash commands, no subagents, no plan mode, no native edit/permission flow.
2. **The user's already-authorized `mcp__claude_ai_*` MCP servers don't carry over to a freshly-spawned `-p` subprocess.** When the user asked "what's on my calendar today," the MCP server replied "Calendar's not connected, run `/mcp`" — but slash commands are disabled in `-p` mode anyway.

The right answer is an **embedded terminal** running `claude` interactively, sharing the user's actual Claude Code session state. No `-p`, no MCP server reconstructed inside Irma, no chat-bubble UX for a tool that's structurally a terminal.

## Decision

1. **New "Claude" tab in the main window** is a panel hosting an `xterm.js` terminal that drives a real `claude` process (interactive, `--dangerously-skip-permissions`) launched in the Irma repo's working directory.
2. **Persona** is set via an appended section in the repo's existing `CLAUDE.md`. Calm/terse/Amit's-dog persona; lists how to reach Irma's projects/tasks via REST.
3. **Projects/tasks** are reached by Claude using its native `Bash` tool to curl Irma's REST API (already running for Local chat on the configured `IRMA_API_HOST:IRMA_API_PORT`). No new MCP server, no new dependencies.
4. **Calendar/mail** are reached by Claude using its already-authorized `mcp__claude_ai_Gmail` and `mcp__claude_ai_Google_Calendar` servers — which work fine in an interactive session.
5. **The chat tab becomes Local-only.** No backend toggle, no `claude_cli` chat backend, no `_HIDDEN_BACKENDS` filter.

## Out of scope

- MCP server for Irma's tools. Discarded.
- Multiple concurrent Claude terminals (single panel, single session).
- Persisting terminal scrollback across app restarts.
- Custom terminal theme beyond what xterm.js gives out of the box.
- Replacing the user's CLAUDE.md content — we only append.
- Re-using the deleted `claude_cli` backend for scripts/tests. If any future need arises, re-introduce as a separate concern.

## What we keep from `feat/chat-tools-parity`

All of this stays — it serves the Local (ollama) chat:

- OAuth scope bump to `calendar.events`.
- `CreateCalendarEventTool`, `ListProjectsTool`, `CreateProjectTool`, `ListTasksTool`, `CreateTaskTool`, `CompleteTaskTool`.
- Tool registration in `app.py`.
- Dynamic system prompt (`_build_system_prompt`) for the Local chat.
- `secret_value_or_none` config helper.

## What we discard

- `ClaudeCliLLM` class in `services/api/src/irma_api/agents/llm.py` and its tests in `tests/test_llm_claude_cli.py`. Replaced by the terminal.
- `_HIDDEN_BACKENDS` + `_STATEFUL_BACKENDS` filter logic in `routers/chat.py`. Chat is single-backend.
- `tests/test_chat_backends_filter.py`. Moot.
- `BACKEND_LABEL`, `backendOptions`, the backend-toggle UI in `apps/desktop/src/main/chat/ChatView.tsx`. Single backend means no picker.
- `backend` field on `ChatRequest`. Single backend means no selection.
- Frontend `localStorage` key `irma.chat.backend`. No longer needed.
- The `BackendInfo` model and `GET /chat/backends` endpoint. Single backend = no listing.

## Architecture

### Embedded terminal

**Frontend** (`apps/desktop/src/main/claude/ClaudeTerminal.tsx`, new):

- Hosts an `xterm.js` `Terminal` instance with `@xterm/addon-fit` for resize.
- Subscribes to a Tauri event channel `claude-pty:data` for stdout/stderr.
- Sends user keystrokes to the backend via Tauri command `claude_pty_write`.
- Sends resize events via Tauri command `claude_pty_resize`.
- On mount, calls `claude_pty_spawn`. On unmount, calls `claude_pty_kill`.

**Backend** (`apps/desktop/src-tauri/src/claude_pty.rs`, new):

- Uses the `portable-pty` crate.
- Single global `Mutex<Option<PtyHandle>>` in app state — only one live session at a time. Spawning when one exists kills the old one.
- `claude_pty_spawn(cwd: String)` → spawns `claude --dangerously-skip-permissions` with `cwd` set to the repo root; opens reader/writer; starts a tokio task that emits `claude-pty:data` events for each chunk read.
- `claude_pty_write(bytes: Vec<u8>)` → writes to PTY stdin.
- `claude_pty_resize(rows: u16, cols: u16)` → writes resize via PTY.
- `claude_pty_kill()` → sends SIGTERM, waits ~2s, then SIGKILL if needed.
- Registered in `lib.rs` via `tauri::Builder::default().invoke_handler(tauri::generate_handler![...])`.

**Tab wiring** (`apps/desktop/src/main/App.tsx`):

- New tab "Claude" alongside the existing tabs. `Tab` union becomes `"projects" | "chat" | "claude" | "brief" | "settings"`.
- Display order: `Brief | Chat | Claude | Projects | Settings` (matching the existing left-to-right convention; Claude sits next to Chat since they're the two conversational surfaces).

### CLAUDE.md additions

Append a section to the repo's existing `CLAUDE.md`:

```markdown
## When invoked through Irma's Claude tab

You are running inside the Irma desktop window's Claude tab. Persona:
calm, terse, slightly proactive — Amit's dog and personal assistant.
Don't perform "dog" — no woofs, no third-person narration. But if Amit
asks who you are, answer honestly: you're his dog, and his assistant.

Irma maintains a Projects + Tasks store. Manage it via the local REST
API (always running while Irma is open):

- Base URL: `http://127.0.0.1:8765/api/v1` (set by IRMA_API_HOST /
  IRMA_API_PORT in `.env`; check there if 8765 is wrong).
- `GET  /projects` — list active projects (`?status=` repeatable).
- `POST /projects` — create. Body: `{"name": "...", "calendar_keywords":
  [...], "target_date": "YYYY-MM-DD", "priority": 1-3}`.
- `PATCH /projects/{id}` — partial update.
- `GET  /tasks?project_id=&status=&due_before=&scheduled_from=&scheduled_to=`
- `POST /tasks` — create. Body: `{"project_id": "...", "title": "...",
  "due_date": "YYYY-MM-DD", "scheduled_for": "YYYY-MM-DD",
  "estimated_minutes": int}`.
- `POST /tasks/{id}/complete` — mark done (idempotent).
- `GET  /brief/today | /week | /month | /overview` — synthesized briefs.

Use `curl -sS` from your Bash tool to read/write. For calendar and mail,
use your already-authorized `mcp__claude_ai_Google_Calendar` and
`mcp__claude_ai_Gmail` servers — Irma does not proxy those.
```

The wording is exact. We append, never replace.

### Launch flags

`claude --dangerously-skip-permissions`. The user explicitly opted into this — bypasses all Claude Code permission prompts so the terminal flow isn't constantly blocked. No `--system-prompt` flag (CLAUDE.md does that). No `--mcp-config` (the user's globally-configured MCPs are picked up automatically). No `-p` (interactive).

**Workdir** is the Irma repo root (parent of `services/` and `apps/`). Detected at app startup via Tauri's `tauri::App::path_resolver` — we resolve the repo root by walking up from the executable until we find `.git`. If detection fails, fall back to the current working directory; log a warning.

### Frontend chat cleanup

`apps/desktop/src/main/chat/ChatView.tsx` is significantly simplified:

- Drop the backends `useEffect` and the backend-toggle UI.
- Drop the `backend` field from the `sendChat` payload.
- Drop `sessionIdRef` (claude_cli is the only backend that required it).
- Keep the new-conversation button (clear messages locally).

`apps/desktop/src/lib/api.ts` likewise drops `getChatBackends` and the `backend` / `sessionId` arguments on `sendChat`.

`apps/desktop/src/lib/types.ts` drops `ChatBackends`.

## Files touched

| File | Status | Purpose |
|------|--------|---------|
| `apps/desktop/src/main/claude/ClaudeTerminal.tsx` | create | xterm.js panel, Tauri event hookup. |
| `apps/desktop/src/main/App.tsx` | modify | Add Claude tab. |
| `apps/desktop/src-tauri/Cargo.toml` | modify | Add `portable-pty` dep. |
| `apps/desktop/src-tauri/src/claude_pty.rs` | create | PTY spawn/IO/resize/kill commands. |
| `apps/desktop/src-tauri/src/lib.rs` | modify | Register the new commands. |
| `apps/desktop/package.json` | modify | Add `@xterm/xterm`, `@xterm/addon-fit`. |
| `apps/desktop/src/main/chat/ChatView.tsx` | modify | Drop backend toggle + session-id. |
| `apps/desktop/src/lib/api.ts` | modify | Drop `getChatBackends`; simplify `sendChat`. |
| `apps/desktop/src/lib/types.ts` | modify | Drop `ChatBackends`. |
| `CLAUDE.md` | modify | Append the "When invoked through Irma's Claude tab" section. |
| `services/api/src/irma_api/agents/llm.py` | modify | Delete `ClaudeCliLLM`; drop CLI binary detection in `build_llm_registry`. |
| `services/api/src/irma_api/routers/chat.py` | modify | Delete `_HIDDEN_BACKENDS`, `_STATEFUL_BACKENDS`, `GET /chat/backends`, `BackendInfo`, `backend`/`session_id` request fields. |
| `services/api/src/irma_api/config.py` | modify | Drop `claude_cli_*` settings if no longer referenced. |
| `services/api/tests/test_llm_claude_cli.py` | delete | Backend gone. |
| `services/api/tests/test_chat_backends_filter.py` | delete | Filter gone. |
| `services/api/tests/test_chat_tool_loop.py` | modify | Drop the `claude_cli`-flavored stub and the backend-listing test. |

## Testing

- **Backend tests:** simplify the chat router suite to single-backend; remove tests for the removed surface. Full pytest stays clean.
- **Frontend tests:** none exist today for the chat view; no regression check needed beyond `npm run build`.
- **Terminal smoke:** manual. The Rust PTY code is mechanical; reviewable by reading. End-to-end test is "launch the app, click the Claude tab, verify a `claude` prompt appears and accepts input."

## Risks

- **`--dangerously-skip-permissions` is a real choice.** The terminal Claude can run any Bash command, edit any file in the workdir, hit the network, all without prompting. The user has accepted this explicitly. I note it here so it isn't a hidden assumption.
- **Repo root detection** could fail on packaged builds (no `.git` next to the exe). Fallback to `tauri::api::path::home_dir()` + a documented `IRMA_CLAUDE_WORKDIR` env override.
- **Terminal/PTY lifecycle:** the spawned `claude` must die when the app quits. Wire a `tauri::WindowEvent::CloseRequested` hook on the main window that calls `claude_pty_kill`.
- **CLAUDE.md drift:** if the user later changes `IRMA_API_PORT`, the appended docs become wrong. We hedge by writing "check .env if 8000 is wrong" in the prompt — Claude can self-correct.
- **xterm.js size:** adds ~150KB gzipped to the bundle. Acceptable.

## Branch strategy

`feat/chat-tools-parity` is a coherent slice and should be merged to `main` as-is — the Local backend genuinely gains read/write calendar + projects/tasks + email. Start the terminal pivot on a fresh `feat/claude-terminal` branch from `main` after merge.
