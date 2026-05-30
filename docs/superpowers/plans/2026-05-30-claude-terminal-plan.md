# Claude Terminal Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Irma's `claude_cli` chat backend with an embedded xterm.js terminal that runs `claude --dangerously-skip-permissions` interactively in the repo workdir. Persona via `CLAUDE.md`, projects/tasks via Irma's REST API, calendar/mail via the user's already-authorized claude.ai MCP servers.

**Architecture:** A new "Claude" tab in the Tauri dashboard hosts an `xterm.js` `Terminal` driven by a Rust PTY (`portable-pty`). The chat tab becomes single-backend (Local only): every claude_cli-specific code path — `ClaudeCliLLM`, `_HIDDEN_BACKENDS`, `_STATEFUL_BACKENDS`, the backend toggle UI, `GET /chat/backends`, the `backend`/`session_id` chat-request fields — gets removed. A short Irma-persona section is appended to the repo's root `CLAUDE.md` so the terminal Claude knows what window it's in and how to reach Irma's REST API.

**Tech Stack:** Tauri v2 (Rust + React), `xterm.js` + `@xterm/addon-fit`, `portable-pty` crate, FastAPI (Python 3.12) for the existing REST API. No new Python dependencies — the projects/tasks/brief endpoints already exist.

**Spec:** `docs/superpowers/specs/2026-05-30-claude-terminal-design.md`

**Branch:** start a fresh `feat/claude-terminal` cut from `main` AFTER merging `feat/chat-tools-parity`. The merge happens in Task 0.

---

## File map

| File | Status | Purpose |
| ---- | ------ | ------- |
| `apps/desktop/src-tauri/Cargo.toml` | modify | Add `portable-pty` + `tokio` (rt + sync features) dependencies. |
| `apps/desktop/src-tauri/src/claude_pty.rs` | create | PTY spawn/IO/resize/kill commands; emits `claude-pty:data` events. |
| `apps/desktop/src-tauri/src/lib.rs` | modify | Register the new `claude_pty.rs` commands; wire shutdown hook. |
| `apps/desktop/package.json` | modify | Add `@xterm/xterm` and `@xterm/addon-fit` runtime deps. |
| `apps/desktop/src/main/claude/ClaudeTerminal.tsx` | create | xterm.js panel; subscribes to PTY events; sends keystrokes/resize. |
| `apps/desktop/src/main/App.tsx` | modify | Add `"claude"` tab; render `ClaudeTerminal` when active. |
| `apps/desktop/src/main/chat/ChatView.tsx` | modify | Drop backend toggle, session-id, `useEffect` for `getChatBackends`. |
| `apps/desktop/src/lib/api.ts` | modify | Drop `getChatBackends`; simplify `sendChat` signature. |
| `apps/desktop/src/lib/types.ts` | modify | Drop `ChatBackends` interface. |
| `CLAUDE.md` | modify | Append the "When invoked through Irma's Claude tab" section. |
| `services/api/src/irma_api/agents/llm.py` | modify | Delete `ClaudeCliLLM`, `ClaudeAuthError`, `_SessionAlreadyInUse`; drop the CLI-binary registration branch from `build_llm_registry`. |
| `services/api/src/irma_api/routers/chat.py` | modify | Delete `_HIDDEN_BACKENDS`, `_STATEFUL_BACKENDS`, `BackendInfo`, `get_backends`, the stateful-skip branch in `post_chat`, `session_id`/`backend` request fields. |
| `services/api/src/irma_api/config.py` | modify | Delete `claude_cli_*` settings if no longer referenced anywhere. |
| `services/api/tests/test_llm_claude_cli.py` | delete | Backend gone. |
| `services/api/tests/test_chat_backends_filter.py` | delete | Filter gone. |
| `services/api/tests/test_chat_tool_loop.py` | modify | Drop the `_StatefulFakeLLM` stub and the `test_get_backends_lists_registry` test. |
| `services/api/tests/test_settings.py` | modify | Drop any `claude_cli_*` assertion. |

---

## Working-directory conventions

- Python commands assume `cd services/api` (or use the absolute path `/Users/amit/Documents/Code/Irma/services/api`).
- Rust + node commands assume `cd apps/desktop`.
- Git commands run from the repo root `/Users/amit/Documents/Code/Irma`.

Do NOT include `Co-Authored-By` lines in commit messages — the harness blocks them.

---

## Task 0: Merge `feat/chat-tools-parity` to `main`; start a fresh branch

**Files:** none modified — purely git topology.

This plan's deletions only make sense if the additions from `feat/chat-tools-parity` are first preserved on `main`.

- [ ] **Step 1: Confirm working tree is clean on `feat/chat-tools-parity`**

```bash
git status
```
Expected: branch `feat/chat-tools-parity`, no uncommitted changes.

- [ ] **Step 2: Run the full backend test suite one more time before merge**

```bash
cd services/api && uv run pytest -q
```
Expected: 199 passed (the count at the head of `feat/chat-tools-parity` after the latest fixes).

- [ ] **Step 3: Fast-forward `main` to the head of the branch**

```bash
git checkout main
git merge --ff-only feat/chat-tools-parity
```
Expected: fast-forward succeeds. If it doesn't (e.g. `main` advanced unexpectedly), STOP and report — do not force-merge.

- [ ] **Step 4: Cut the new branch**

```bash
git checkout -b feat/claude-terminal
git status
```
Expected: branch `feat/claude-terminal` based on the new `main`.

- [ ] **Step 5: Run baseline tests on the new branch**

```bash
cd services/api && uv run pytest -q
```
Expected: 199 passed.

---

## Task 1: Strip the `claude_cli` backend from the API

**Files:**
- Modify: `services/api/src/irma_api/agents/llm.py`
- Modify: `services/api/src/irma_api/routers/chat.py`
- Modify: `services/api/src/irma_api/config.py`
- Delete: `services/api/tests/test_llm_claude_cli.py`
- Delete: `services/api/tests/test_chat_backends_filter.py`
- Modify: `services/api/tests/test_chat_tool_loop.py`
- Modify: `services/api/tests/test_settings.py`

We do the deletions FIRST so the surface area shrinks before we touch the desktop side. Every later test that exercised the deleted code is removed in this task.

- [ ] **Step 1: Delete `ClaudeCliLLM` and helpers from `agents/llm.py`**

In `services/api/src/irma_api/agents/llm.py`:
- Remove the class `ClaudeCliLLM` and the supporting top-level classes `ClaudeAuthError` and `_SessionAlreadyInUse`.
- Remove the `ClaudeCliLLM` registration branch inside `build_llm_registry` (the `if shutil.which(...)` block). The function should now register only `anthropic` (if API key set) and `ollama`.
- Drop the `import shutil` line if it was used solely for `shutil.which` and isn't referenced elsewhere in the file.
- Leave the rest of the file (Protocol, ChatTurn, AnthropicLLM, OllamaLLM, ToolCall types) untouched.

The new tail of `build_llm_registry` (replacing the existing claude_cli block) is just:

```python
    desired = settings.irma_llm_backend
    default: str | None
    if desired in registry:
        default = desired
    elif registry:
        default = next(iter(registry))
        logger.warning("llm.default_fallback", desired=desired, chosen=default)
    else:
        default = None

    return registry, default
```

- [ ] **Step 2: Strip the multi-backend surface from `routers/chat.py`**

In `services/api/src/irma_api/routers/chat.py`:
- Remove `_STATEFUL_BACKENDS` and `_HIDDEN_BACKENDS` constants.
- Remove the `BackendInfo` Pydantic model.
- Remove the `get_backends` route handler.
- Remove the `backend` and `session_id` fields from `ChatRequest`. Replace its body with:

```python
class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
```

- Simplify `_resolve_llm` to ignore any `requested` argument (it no longer exists). Replace the function with:

```python
def _resolve_llm(request: Request) -> LLMClient:
    registry: dict[str, LLMClient] = getattr(request.app.state, "llm_registry", {}) or {}
    default: str | None = getattr(request.app.state, "default_backend", None)

    if not registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM backend not configured — set IRMA_LLM_BACKEND and creds",
        )
    if default is None or default not in registry:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="no default LLM backend available",
        )
    return registry[default]
```

- Simplify `post_chat` to drop the `skip_tools` branch entirely. The handler shape becomes:

```python
@router.post("/chat", response_model=ChatResponse)
async def post_chat(request: Request, body: ChatRequest) -> ChatResponse:
    llm = _resolve_llm(request)

    bus: StateBus = request.app.state.bus
    tools: ToolRegistry | None = getattr(request.app.state, "tools", None)

    turns: list[ChatTurn] = [
        ChatTurn(role=m.role, content=m.content) for m in body.messages
    ]

    await bus.publish(AgentState.THINKING)
    reply: str | None = None
    try:
        for _iteration in range(MAX_TOOL_ITERATIONS):
            tool_specs = tools.specs() if tools is not None else []
            outcome = await llm.complete(
                system=_build_system_prompt(tools.names() if tools else []),
                messages=turns,
                tools=tool_specs or None,
                max_tokens=800,
            )
            if isinstance(outcome, TextResult):
                reply = outcome.text
                break
            assert isinstance(outcome, ToolCallResult)
            if tools is None:
                logger.error("chat.tool_call_without_registry")
                reply = _STUCK_REPLY
                break
            turns.append(
                ChatTurn(
                    role="assistant",
                    content=outcome.preface,
                    tool_calls=outcome.calls,
                )
            )
            results = await _run_tool_calls(tools, outcome.calls)
            turns.append(
                ChatTurn(role="user", content="", tool_results=results)
            )
        if reply is None:
            logger.error("chat.tool_loop_exceeded", iterations=MAX_TOOL_ITERATIONS)
            reply = _STUCK_REPLY
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("chat.failed", backend=llm.backend)
        await bus.publish(AgentState.ALERT)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"chat backend failed: {exc}",
        ) from exc

    await bus.publish(AgentState.IDLE)
    return ChatResponse(reply=reply, backend=llm.backend, model=llm.model)
```

- Drop the `import uuid` line at the top of the file if it was used only by the deleted UUID validation. Drop the `from typing import Final` import if no other `Final` annotations remain (they do — `MAX_TOOL_ITERATIONS`).

- [ ] **Step 3: Drop the unused `claude_cli_*` settings from `config.py`**

In `services/api/src/irma_api/config.py`, remove every field whose name starts with `claude_cli_` (binary path, model, timeout) and any imports they alone used. If there's a comment block above them, remove that too. Do NOT touch any other settings.

- [ ] **Step 4: Delete the dead test files**

```bash
rm services/api/tests/test_llm_claude_cli.py
rm services/api/tests/test_chat_backends_filter.py
```

- [ ] **Step 5: Trim `test_chat_tool_loop.py`**

Open `services/api/tests/test_chat_tool_loop.py` and:
- Remove the `_StatefulFakeLLM` class (the stub used to fake the claude_cli stateful backend).
- Remove `test_get_backends_lists_registry` entirely — the endpoint no longer exists.
- If the `_build_app` helper signature accepts a `registry` and `default` parameter that's only used by the removed test, simplify it to its single-backend form (whatever shape lets the remaining tests still pass). Mechanical edit: keep removing surface area until the remaining tests don't reference any deleted symbol.

- [ ] **Step 6: Trim `test_settings.py`**

In `services/api/tests/test_settings.py`, delete any assertion that mentions `claude_cli_binary`, `claude_cli_model`, `claude_cli_timeout_seconds`, or similar. If no assertion was made about those fields, this step is a no-op — verify with grep:

```bash
cd services/api && grep -n "claude_cli" tests/test_settings.py
```
Expected: no matches.

- [ ] **Step 7: Run the full backend suite**

```bash
cd services/api && uv run pytest -q
```
Expected: clean. If any tests fail, the failures should reference removed names — adjust those tests to drop the references or delete the test if it covered only the removed surface.

- [ ] **Step 8: Lint + type-check**

```bash
cd services/api && uv run ruff check src/ tests/ && uv run mypy --strict src/
```
Expected: no NEW errors (the two pre-existing items in `tools/resend.py:43` and `tests/test_lead_agent_horizons.py:3` may still show).

- [ ] **Step 9: Commit**

```bash
git add services/api/
git commit -m "feat(chat): remove claude_cli backend; chat becomes single-backend"
```

---

## Task 2: Strip the backend toggle from the desktop chat view

**Files:**
- Modify: `apps/desktop/src/main/chat/ChatView.tsx`
- Modify: `apps/desktop/src/lib/api.ts`
- Modify: `apps/desktop/src/lib/types.ts`

We're paying off the frontend half of the chat simplification before adding the new Claude tab.

- [ ] **Step 1: Drop `getChatBackends` and simplify `sendChat` in `api.ts`**

In `apps/desktop/src/lib/api.ts`:
- Delete the `getChatBackends` function (currently the last named export).
- Drop the `ChatBackends` import from `./types`.
- Simplify the `sendChat` signature to:

```ts
export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
  return jsonOrThrow(
    await fetch(url("/api/v1/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    }),
  );
}
```

- [ ] **Step 2: Drop `ChatBackends` from `types.ts`**

In `apps/desktop/src/lib/types.ts`, delete the `ChatBackends` interface block. Leave every other type untouched.

- [ ] **Step 3: Strip the toggle from `ChatView.tsx`**

In `apps/desktop/src/main/chat/ChatView.tsx`:
- Remove `BACKEND_STORAGE_KEY`, `BACKEND_LABEL`, `labelFor`.
- Remove `ChatBackends` from the `import type` list.
- Remove `getChatBackends` from the imports.
- Remove the `backends`, `selected` `useState` declarations.
- Remove `sessionIdRef` (no backend requires it any more).
- Remove the `useEffect` that fetched `getChatBackends` and persisted the chosen backend.
- Remove the `pickBackend` function.
- Remove the entire backend-picker JSX block (the `<div>` containing the toggle buttons; everything from `{backendOptions.length > 1 && (` to the matching `)}`).
- Remove the `clearConversation` regeneration of `sessionIdRef.current` — the function just clears messages, meta, and error.
- Update the `submit` call to `sendChat(next)` (no second arg).
- Remove `backendOptions = useMemo(...)` and any other dead helpers.

The resulting file should be substantially shorter; expected layout: header strip with the "new conversation" link (when messages exist), message list, input textarea, send button, meta footer. The persona's claim "Ask Irma anything..." prompt stays.

- [ ] **Step 4: Frontend type-check and build**

```bash
cd apps/desktop && npm run build
```
Expected: TypeScript compiles, Vite emits a `dist/` bundle, no errors.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src/lib/api.ts apps/desktop/src/lib/types.ts apps/desktop/src/main/chat/ChatView.tsx
git commit -m "feat(chat-ui): drop backend toggle and session-id plumbing"
```

---

## Task 3: Add Rust PTY commands for the Claude terminal

**Files:**
- Modify: `apps/desktop/src-tauri/Cargo.toml`
- Create: `apps/desktop/src-tauri/src/claude_pty.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs`

This is the largest Rust file we'll add. The PTY layer holds a single `Mutex<Option<PtyState>>` in app state and exposes four Tauri commands.

- [ ] **Step 1: Add Rust dependencies**

In `apps/desktop/src-tauri/Cargo.toml`, replace the `[dependencies]` block with:

```toml
[dependencies]
tauri = { version = "2", features = ["macos-private-api", "tray-icon"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
portable-pty = "0.8"
tokio = { version = "1", features = ["rt", "sync", "macros", "io-util"] }
```

(Adds `portable-pty` and `tokio` only. Everything else stays identical.)

- [ ] **Step 2: Create `claude_pty.rs`**

Create `apps/desktop/src-tauri/src/claude_pty.rs` with:

```rust
//! Embedded Claude Code terminal.
//!
//! The frontend ClaudeTerminal panel drives a real `claude --dangerously-skip-permissions`
//! process through a pseudoterminal so the user gets the full interactive
//! Claude Code experience (streaming, slash commands, MCP servers) inside
//! the Irma window.
//!
//! Lifetime: at most one PTY at a time, held in app state. Closing the panel
//! (or quitting the app) kills the process via SIGTERM, then SIGKILL on
//! timeout. The panel re-spawns on remount.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, State};

const PTY_DATA_EVENT: &str = "claude-pty:data";
const PTY_EXIT_EVENT: &str = "claude-pty:exit";

#[derive(Default)]
pub struct ClaudePty(pub Mutex<Option<PtyState>>);

pub struct PtyState {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    child: Box<dyn Child + Send>,
}

#[derive(Serialize, Clone)]
struct PtyExit {
    code: Option<i32>,
}

/// Walk up from `start` looking for a directory containing `.git`. Falls
/// back to `start` itself if none found, so we never refuse to spawn.
fn find_repo_root(start: PathBuf) -> PathBuf {
    let mut cur = start.clone();
    loop {
        if cur.join(".git").exists() {
            return cur;
        }
        match cur.parent() {
            Some(p) => cur = p.to_path_buf(),
            None => return start,
        }
    }
}

#[tauri::command]
pub fn claude_pty_spawn(
    app: AppHandle,
    state: State<'_, ClaudePty>,
    rows: u16,
    cols: u16,
) -> Result<(), String> {
    // Kill any existing session before opening a new one.
    {
        let mut slot = state.0.lock().map_err(|e| e.to_string())?;
        if let Some(mut prev) = slot.take() {
            let _ = prev.child.kill();
        }
    }

    // Resolve workdir: env override → repo root walking up from CWD → CWD.
    let workdir = std::env::var("IRMA_CLAUDE_WORKDIR")
        .ok()
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::current_dir()
                .map(find_repo_root)
                .unwrap_or_else(|_| PathBuf::from("."))
        });

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 })
        .map_err(|e| format!("openpty failed: {e}"))?;

    let binary = std::env::var("IRMA_CLAUDE_BINARY").unwrap_or_else(|_| "claude".to_string());
    let mut cmd = CommandBuilder::new(binary);
    cmd.arg("--dangerously-skip-permissions");
    cmd.cwd(&workdir);
    // Inherit the user's interactive shell environment as best we can.
    for (k, v) in std::env::vars() {
        cmd.env(k, v);
    }

    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| format!("spawn claude failed: {e}"))?;
    drop(pair.slave);

    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| format!("clone pty reader failed: {e}"))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| format!("take pty writer failed: {e}"))?;

    // Reader thread: blocking read on the PTY, emit each chunk to the
    // frontend as `claude-pty:data` events.
    let reader_app = app.clone();
    thread::spawn(move || {
        let mut buf = [0u8; 4096];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let chunk = String::from_utf8_lossy(&buf[..n]).into_owned();
                    if let Err(err) = reader_app.emit(PTY_DATA_EVENT, chunk) {
                        eprintln!("[claude_pty] emit data failed: {err}");
                        break;
                    }
                }
                Err(err) => {
                    eprintln!("[claude_pty] read err: {err}");
                    break;
                }
            }
        }
    });

    // Wait thread: blocks until the child exits so we can notify the UI.
    // We cannot move the Child into the wait thread because state needs
    // to hold it for kill(); instead, hand off a clone of the AppHandle
    // and rely on the reader thread to terminate when the PTY closes.

    {
        let mut slot = state.0.lock().map_err(|e| e.to_string())?;
        *slot = Some(PtyState {
            master: pair.master,
            writer,
            child,
        });
    }

    eprintln!(
        "[claude_pty] spawned in {workdir:?} ({rows}x{cols})",
        workdir = workdir
    );
    Ok(())
}

#[tauri::command]
pub fn claude_pty_write(state: State<'_, ClaudePty>, data: String) -> Result<(), String> {
    let mut slot = state.0.lock().map_err(|e| e.to_string())?;
    let Some(pty) = slot.as_mut() else {
        return Err("no claude pty session".into());
    };
    pty.writer
        .write_all(data.as_bytes())
        .map_err(|e| e.to_string())?;
    pty.writer.flush().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn claude_pty_resize(
    state: State<'_, ClaudePty>,
    rows: u16,
    cols: u16,
) -> Result<(), String> {
    let slot = state.0.lock().map_err(|e| e.to_string())?;
    let Some(pty) = slot.as_ref() else {
        return Err("no claude pty session".into());
    };
    pty.master
        .resize(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 })
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn claude_pty_kill(
    app: AppHandle,
    state: State<'_, ClaudePty>,
) -> Result<(), String> {
    let mut slot = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(mut pty) = slot.take() {
        let _ = pty.child.kill();
        // Give it a moment to flush; portable-pty's `kill()` already sends
        // SIGKILL on Unix, but yield to let the reader thread observe EOF.
        thread::sleep(Duration::from_millis(50));
        let code = pty.child.wait().ok().and_then(|s| s.exit_code().try_into().ok());
        let _ = app.emit(PTY_EXIT_EVENT, PtyExit { code });
    }
    Ok(())
}
```

- [ ] **Step 3: Register the new commands and state in `lib.rs`**

In `apps/desktop/src-tauri/src/lib.rs`, replace the file contents with:

```rust
mod claude_pty;
mod tray;
mod windows;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(claude_pty::ClaudePty::default())
        .invoke_handler(tauri::generate_handler![
            windows::position_companion,
            windows::toggle_main,
            windows::get_companion_bounds,
            windows::set_companion_pos,
            claude_pty::claude_pty_spawn,
            claude_pty::claude_pty_write,
            claude_pty::claude_pty_resize,
            claude_pty::claude_pty_kill,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            windows::wire_windows(app)?;
            tray::init(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    if let Some(state) = window.app_handle().try_state::<claude_pty::ClaudePty>() {
                        if let Ok(mut slot) = state.0.lock() {
                            if let Some(mut pty) = slot.take() {
                                let _ = pty.child.kill();
                            }
                        }
                    }
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Irma");
}
```

(The Destroyed handler kills any orphan PTY when the main window is destroyed — covers app shutdown.)

- [ ] **Step 4: Compile the Rust side without launching the app**

```bash
cd apps/desktop/src-tauri && cargo check
```
Expected: clean build (warnings OK; errors are not). First run downloads `portable-pty` + `tokio` and will take a couple of minutes.

If `cargo check` complains that `tokio` is unused, drop it from `Cargo.toml` — we ended up not needing it for the synchronous PTY thread. Run `cargo check` again and confirm clean.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/Cargo.toml \
        apps/desktop/src-tauri/Cargo.lock \
        apps/desktop/src-tauri/src/claude_pty.rs \
        apps/desktop/src-tauri/src/lib.rs
git commit -m "feat(desktop): add Rust PTY commands for embedded Claude terminal"
```

---

## Task 4: Add the xterm.js panel and Claude tab

**Files:**
- Modify: `apps/desktop/package.json`
- Create: `apps/desktop/src/main/claude/ClaudeTerminal.tsx`
- Modify: `apps/desktop/src/main/App.tsx`

- [ ] **Step 1: Install xterm dependencies**

```bash
cd apps/desktop && npm install @xterm/xterm@^5 @xterm/addon-fit@^0.10
```
Expected: `package.json` and `package-lock.json` updated.

- [ ] **Step 2: Create `ClaudeTerminal.tsx`**

Create `apps/desktop/src/main/claude/ClaudeTerminal.tsx`:

```tsx
import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const DATA_EVENT = "claude-pty:data";
const EXIT_EVENT = "claude-pty:exit";

export function ClaudeTerminal() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const disposeRef = useRef<UnlistenFn[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      fontFamily:
        '"JetBrains Mono", "Menlo", "DejaVu Sans Mono", "Courier New", monospace',
      fontSize: 13,
      lineHeight: 1.15,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 5000,
      theme: {
        background: "#0f1117",
        foreground: "#d8dee4",
        cursor: "#d8dee4",
      },
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const { rows, cols } = term;

    void invoke("claude_pty_spawn", { rows, cols }).catch((e: unknown) => {
      term.writeln(`\r\n[irma] failed to spawn claude: ${String(e)}\r\n`);
    });

    const onDataDisposable = term.onData((chunk: string) => {
      void invoke("claude_pty_write", { data: chunk }).catch((e: unknown) =>
        console.error("[claude_pty] write failed:", e),
      );
    });

    void listen<string>(DATA_EVENT, (event) => {
      term.write(event.payload);
    }).then((unlisten) => disposeRef.current.push(unlisten));

    void listen<{ code: number | null }>(EXIT_EVENT, (event) => {
      term.writeln(
        `\r\n[irma] claude exited (code ${event.payload.code ?? "?"})\r\n`,
      );
    }).then((unlisten) => disposeRef.current.push(unlisten));

    const onResize = () => {
      try {
        fit.fit();
        void invoke("claude_pty_resize", { rows: term.rows, cols: term.cols });
      } catch (e: unknown) {
        console.error("[claude_pty] resize failed:", e);
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      onDataDisposable.dispose();
      disposeRef.current.forEach((un) => {
        try {
          un();
        } catch {
          /* noop */
        }
      });
      disposeRef.current = [];
      void invoke("claude_pty_kill").catch(() => undefined);
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      style={{ background: "#0f1117" }}
    />
  );
}
```

- [ ] **Step 3: Wire the Claude tab into `App.tsx`**

In `apps/desktop/src/main/App.tsx`:

(a) Add the import near the other tab imports:

```ts
import { ClaudeTerminal } from "./claude/ClaudeTerminal";
```

(b) Widen the `Tab` union:

```ts
type Tab = "projects" | "chat" | "claude" | "brief" | "settings";
```

(c) Add a tab render branch — insert this block right after the existing `chat` branch:

```tsx
        {tab === "claude" && <ClaudeTerminal />}
```

(d) Add a Tab button in the `Header` nav, in this order so it sits between Chat and Brief:

```tsx
        <Tab id="chat"   current={tab} onClick={onTabChange}>Chat</Tab>
        <Tab id="claude" current={tab} onClick={onTabChange}>Claude</Tab>
        <Tab id="brief"  current={tab} onClick={onTabChange}>Brief</Tab>
```

No other changes to `App.tsx`. The Settings tab and the refresh button stay where they were.

- [ ] **Step 4: Frontend type-check + build**

```bash
cd apps/desktop && npm run build
```
Expected: TypeScript compiles, build succeeds. `@xterm/xterm/css/xterm.css` is resolved via Vite's CSS import — no extra config needed.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/package.json apps/desktop/package-lock.json \
        apps/desktop/src/main/claude/ClaudeTerminal.tsx \
        apps/desktop/src/main/App.tsx
git commit -m "feat(desktop): add Claude tab hosting an xterm.js panel"
```

---

## Task 5: Append the Irma section to `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (repo root)

The terminal Claude reads the repo's `CLAUDE.md` automatically. We append a small section so it knows it's running inside the Irma window and how to reach the REST API for projects/tasks.

- [ ] **Step 1: Append the section**

Open `CLAUDE.md` at the repo root. Scroll to the end of the file. Append:

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

Verify with `tail -25 CLAUDE.md` that the new section is the last thing in the file. Do NOT edit anything above it.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): persona + REST endpoints for the Claude tab"
```

---

## Task 6: Full verification

**Files:** none modified — pure verification.

- [ ] **Step 1: Full backend tests**

```bash
cd services/api && uv run pytest -q
```
Expected: clean (a few tests fewer than the 199 baseline since `test_llm_claude_cli.py` and `test_chat_backends_filter.py` were deleted in Task 1; expect ~175–180 passing depending on exact counts).

- [ ] **Step 2: Backend lint + type-check**

```bash
cd services/api && uv run ruff check src/ tests/ && uv run mypy --strict src/
```
Expected: no NEW errors (two pre-existing items may remain).

- [ ] **Step 3: Frontend build**

```bash
cd apps/desktop && npm run build
```
Expected: clean.

- [ ] **Step 4: Rust check**

```bash
cd apps/desktop/src-tauri && cargo check
```
Expected: clean.

- [ ] **Step 5: Confirm no stale references to the deleted symbols**

```bash
grep -rn "claude_cli\|ClaudeCliLLM\|ClaudeAuthError\|_HIDDEN_BACKENDS\|_STATEFUL_BACKENDS\|getChatBackends\|ChatBackends\|BACKEND_LABEL\|sessionIdRef" services/api/src services/api/tests apps/desktop/src apps/desktop/src-tauri 2>/dev/null
```
Expected: no matches. (Matches in `docs/` are fine — those are historical specs/plans.)

---

## Task 7: Manual smoke (operator-only)

This is run by the maintainer after deploy; list it so it isn't forgotten.

- [ ] **Step 1: Launch the dev stack**

In two separate terminals:

```bash
# Terminal 1 — Irma API
cd services/api && uv run irma-api
```

```bash
# Terminal 2 — Irma desktop
cd apps/desktop && npm run tauri dev
```

- [ ] **Step 2: Open the Claude tab**

Click the Irma sprite to open the main window. Click the **Claude** tab. Expected: a black terminal area, then within ~2 seconds the Claude Code welcome prompt appears.

- [ ] **Step 3: Exercise the four key flows**

In the Claude terminal, ask each in turn:

  - "What's on my calendar today?" — expect Claude to call `mcp__claude_ai_Google_Calendar` and reply with real events.
  - "Email me a one-line note: 'terminal smoke working'." — expect Claude to call `mcp__claude_ai_Gmail` and confirm.
  - "List my active projects." — expect Claude to `curl -sS http://127.0.0.1:8765/api/v1/projects` (you'll see the command run) and pretty-print the result.
  - "Add a task to <project>: read the Sora 2 paper, due Friday." — expect a `curl -X POST` against `/api/v1/tasks` and confirmation.

- [ ] **Step 4: Verify Chat tab still works**

Click the **Chat** tab. Send "hi" — expect a reply from Local (ollama) using Irma's own tools. No backend toggle should appear; only the conversation surface and a "new conversation" link once messages exist.

- [ ] **Step 5: Verify lifecycle**

Switch back to the Claude tab — terminal should still be live with prior scrollback. Close the main window (× button). Open it again by clicking the sprite. Expected: terminal **re-spawns** fresh (it does NOT preserve state across panel unmount — that's by design for v1; we can revisit if it matters).

Quit Irma entirely via the tray icon. Expected: the `claude` process exits cleanly (verify with `pgrep -lf claude` showing nothing related to the spawned session).

---

## Notes for the implementer

- **No TDD for the Rust PTY code.** PTY behavior is hard to unit-test without a real terminal; the manual smoke in Task 7 covers it. Subagents should not invent fake harnesses — review by reading.
- **No TDD for the xterm.js component.** Same reason. Build verification (Task 4) catches API misuse; the smoke catches behavior.
- **The deletions in Task 1 ARE TDD.** Run the existing tests; let them surface every place still calling a removed symbol; fix those call sites; re-run.
- **If the Rust step in Task 3 hits a `portable-pty` compile error**, check that the user's macOS is on a recent enough Xcode CLT (the crate uses `libc`'s pty bindings). Recovery: install/update `xcode-select --install`.
- **Permission grants for the spawned `claude`:** because we pass `--dangerously-skip-permissions`, the spawned process bypasses ALL Claude Code permission prompts. The user has accepted this explicitly. Do not silently change that flag.
- **Repo root detection:** the Rust `find_repo_root` walks up from the executable's CWD looking for `.git`. In `tauri dev` mode CWD is `apps/desktop`, and walking up finds `/Users/amit/Documents/Code/Irma` — correct. In packaged builds, CWD is the user's launch directory; if that's not under the repo, the env override `IRMA_CLAUDE_WORKDIR=/Users/amit/Documents/Code/Irma` covers it. Document this in the operator-side `.env.example` if needed (deferred — not in this plan).
