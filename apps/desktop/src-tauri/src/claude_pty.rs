//! Embedded Claude Code terminal.
//!
//! The frontend ClaudeTerminal panel drives a real `claude --dangerously-skip-permissions`
//! process through a pseudoterminal so the user gets the full interactive
//! Claude Code experience (streaming, slash commands, MCP servers) inside
//! the Irma window.
//!
//! Lifetime: at most one PTY at a time, held in app state. We keep a
//! `ChildKiller` handle in `PtyState` and hand the owned `Child` to a
//! dedicated wait thread, so both natural exits (user types `/exit`,
//! claude crashes) and forced kills emit a single `claude-pty:exit` event
//! through the same code path.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::Mutex;
use std::thread;

use portable_pty::{native_pty_system, ChildKiller, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

const PTY_DATA_EVENT: &str = "claude-pty:data";
const PTY_EXIT_EVENT: &str = "claude-pty:exit";

#[derive(Default)]
pub struct ClaudePty(pub Mutex<Option<PtyState>>);

pub struct PtyState {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    pub killer: Box<dyn ChildKiller + Send + Sync>,
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
    // Kill any existing session before opening a new one. The previous wait
    // thread will observe exit and emit `claude-pty:exit` — harmless even if
    // the frontend is about to re-mount, because the new terminal won't have
    // subscribed yet.
    {
        let mut slot = state.0.lock().map_err(|e| e.to_string())?;
        if let Some(mut prev) = slot.take() {
            let _ = prev.killer.kill();
        }
    }

    // Resolve workdir: env override → repo root walking up from CWD →
    // ~/Documents/Code/Irma (default when launched from a .app bundle where
    // CWD is not inside the repo, so CLAUDE.md with the Irma persona loads).
    let home = std::env::var("HOME").unwrap_or_default();
    let workdir = std::env::var("IRMA_CLAUDE_WORKDIR")
        .ok()
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::current_dir()
                .ok()
                .map(find_repo_root)
                .filter(|p| p.join(".git").exists())
                .unwrap_or_else(|| PathBuf::from(format!("{home}/Documents/Code/Irma")))
        });

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize { rows, cols, pixel_width: 0, pixel_height: 0 })
        .map_err(|e| format!("openpty failed: {e}"))?;

    // Resolve the claude binary. GUI .app bundles have a stripped PATH so we
    // must find it by absolute path rather than relying on PATH lookup.
    let binary = std::env::var("IRMA_CLAUDE_BINARY").unwrap_or_else(|_| {
        let candidates = [
            format!("{home}/.local/bin/claude"),
            "/opt/homebrew/bin/claude".to_string(),
            "/usr/local/bin/claude".to_string(),
        ];
        candidates
            .iter()
            .find(|p| std::path::Path::new(p.as_str()).exists())
            .cloned()
            .unwrap_or_else(|| "claude".to_string())
    });

    let mut cmd = CommandBuilder::new(&binary);
    cmd.arg("--dangerously-skip-permissions");
    // Pin Sonnet (latest) at medium effort so the in-Irma session stays fast and
    // cheap. Heavy reasoning belongs in Amit's own Claude Code window.
    cmd.arg("--model");
    cmd.arg("sonnet");
    cmd.arg("--effort");
    cmd.arg("medium");
    cmd.cwd(&workdir);
    // Inherit the parent environment, then patch PATH so tools like node, npm,
    // git, uv, etc. resolve correctly inside the PTY session.
    for (k, v) in std::env::vars() {
        cmd.env(k, v);
    }
    let rich_path = format!(
        "{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    );
    cmd.env("PATH", rich_path);

    let mut child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| format!("spawn claude failed: {e}"))?;
    drop(pair.slave);

    let killer = child.clone_killer();

    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| format!("clone pty reader failed: {e}"))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| format!("take pty writer failed: {e}"))?;

    // Reader thread: blocking read on the PTY, emit each chunk to the
    // frontend as `claude-pty:data` events. Exits cleanly on EOF (which
    // happens when the child dies and the slave side closes).
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

    // Wait thread: blocks on the owned Child until it exits (naturally OR
    // because claude_pty_kill / app shutdown invoked the killer). Emits
    // PTY_EXIT_EVENT exactly once when the process terminates.
    let wait_app = app.clone();
    thread::spawn(move || {
        let code = child
            .wait()
            .ok()
            .and_then(|s| i32::try_from(s.exit_code()).ok());
        if let Err(err) = wait_app.emit(PTY_EXIT_EVENT, PtyExit { code }) {
            eprintln!("[claude_pty] emit exit failed: {err}");
        }
    });

    {
        let mut slot = state.0.lock().map_err(|e| e.to_string())?;
        *slot = Some(PtyState {
            master: pair.master,
            writer,
            killer,
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
pub fn claude_pty_kill(state: State<'_, ClaudePty>) -> Result<(), String> {
    let mut slot = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(mut pty) = slot.take() {
        // The wait thread will emit PTY_EXIT_EVENT once the process actually
        // dies — kill() is the trigger, not the announcement.
        let _ = pty.killer.kill();
    }
    Ok(())
}
