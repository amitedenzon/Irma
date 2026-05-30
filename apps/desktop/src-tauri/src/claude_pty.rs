//! Embedded Claude Code terminal.
//!
//! The frontend ClaudeTerminal panel drives a real `claude --dangerously-skip-permissions`
//! process through a pseudoterminal so the user gets the full interactive
//! Claude Code experience (streaming, slash commands, MCP servers) inside
//! the Irma window.
//!
//! Lifetime: at most one PTY at a time, held in app state. Closing the panel
//! (or quitting the app) kills the process via the portable-pty Child::kill
//! API. The panel re-spawns on remount.

use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use portable_pty::{native_pty_system, Child, CommandBuilder, MasterPty, PtySize};
use serde::Serialize;
use tauri::{AppHandle, Emitter, State};

const PTY_DATA_EVENT: &str = "claude-pty:data";
const PTY_EXIT_EVENT: &str = "claude-pty:exit";

#[derive(Default)]
pub struct ClaudePty(pub Mutex<Option<PtyState>>);

pub struct PtyState {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    pub child: Box<dyn Child + Send>,
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
        let code = pty
            .child
            .wait()
            .ok()
            .and_then(|s| i32::try_from(s.exit_code()).ok());
        let _ = app.emit(PTY_EXIT_EVENT, PtyExit { code });
    }
    Ok(())
}
