mod claude_pty;
mod tray;
mod windows;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconEvent},
    Emitter, Manager,
};

/// Shared flag — true while a native file/folder dialog is open.
#[derive(Default)]
pub struct DialogOpen(pub Arc<AtomicBool>);

/// Handle to the spawned FastAPI backend process.
#[derive(Default)]
pub struct BackendProcess(pub Mutex<Option<std::process::Child>>);

/// Spawn `uv run uvicorn irma_api.app:create_app --factory --port 8765` from
/// the services/api directory. Stdout/stderr are appended to ~/Library/Logs/Irma/api.log.
fn spawn_backend() -> Option<std::process::Child> {
    let home = std::env::var("HOME").unwrap_or_default();

    let api_dir = std::env::var("IRMA_API_DIR")
        .unwrap_or_else(|_| format!("{home}/Documents/Code/Irma/services/api"));

    // Prefer an explicit override, then known install locations.
    // GUI .app bundles get a stripped PATH (/usr/bin:/bin only), so we must
    // resolve uv by absolute path rather than relying on PATH lookup.
    let uv_candidates = [
        std::env::var("IRMA_UV_PATH").unwrap_or_default(),
        format!("{home}/.local/bin/uv"),
        "/opt/homebrew/bin/uv".to_string(),
        "/usr/local/bin/uv".to_string(),
    ];
    let uv = uv_candidates
        .iter()
        .find(|p| !p.is_empty() && std::path::Path::new(p.as_str()).exists())
        .cloned()?;

    let log_dir = format!("{home}/Library/Logs/Irma");
    let _ = std::fs::create_dir_all(&log_dir);

    // Write a launch-attempt line so we can confirm spawn_backend was called.
    let _ = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(format!("{log_dir}/api.log"))
        .map(|mut f| {
            use std::io::Write;
            let _ = writeln!(f, "\n==== backend spawn attempt: uv={uv} dir={api_dir} ====");
        });

    let log_out = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(format!("{log_dir}/api.log"))
        .ok()?;
    let log_err = log_out.try_clone().ok()?;

    // Pass a rich PATH so uv can find python and other tools it needs.
    let path = format!(
        "{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    );

    std::process::Command::new(&uv)
        .args(["run", "uvicorn", "irma_api.app:create_app", "--factory", "--port", "8765"])
        .current_dir(&api_dir)
        .env("HOME", &home)
        .env("PATH", &path)
        .stdout(log_out)
        .stderr(log_err)
        .spawn()
        .map_err(|e| {
            let _ = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(format!("{home}/Library/Logs/Irma/api.log"))
                .map(|mut f| {
                    use std::io::Write;
                    let _ = writeln!(f, "==== spawn FAILED: {e} ====");
                });
        })
        .ok()
}

/// Open a folder picker dialog, briefly activating the app so macOS allows it.
#[tauri::command]
async fn browse_folder(
    app: tauri::AppHandle,
    dialog_open: tauri::State<'_, DialogOpen>,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    dialog_open.0.store(true, Ordering::Release);

    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(tauri::ActivationPolicy::Regular);

    let (tx, rx) = std::sync::mpsc::channel();
    app.dialog().file().pick_folder(move |path| {
        let _ = tx.send(path);
    });
    let result = rx.recv().map_err(|e| e.to_string())?;

    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(tauri::ActivationPolicy::Accessory);

    dialog_open.0.store(false, Ordering::Release);

    Ok(result.map(|p| p.to_string()))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(claude_pty::ClaudePty::default())
        .manage(DialogOpen::default())
        .manage(BackendProcess::default())
        .invoke_handler(tauri::generate_handler![
            windows::position_companion,
            windows::toggle_main,
            windows::is_main_visible,
            windows::is_main_active,
            windows::get_companion_bounds,
            windows::set_companion_pos,
            windows::show_companion_context_menu,
            browse_folder,
            claude_pty::claude_pty_spawn,
            claude_pty::claude_pty_write,
            claude_pty::claude_pty_resize,
            claude_pty::claude_pty_kill,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            // Spawn the FastAPI backend.
            if let Ok(mut slot) = app.state::<BackendProcess>().0.lock() {
                *slot = spawn_backend();
            }

            // Handle companion context-menu placement selections.
            app.on_menu_event(|app, event| {
                match event.id().as_ref() {
                    "companion_left_of_dock" => {
                        let _ = app.emit("companion:placement", "left-of-dock");
                    }
                    "companion_on_dock" => {
                        let _ = app.emit("companion:placement", "on-dock");
                    }
                    "companion_right_of_dock" => {
                        let _ = app.emit("companion:placement", "right-of-dock");
                    }
                    _ => {}
                }
            });

            windows::wire_windows(app)?;
            tray::init(app.handle())?;

            // Global tray icon event listener — required on macOS with
            // ActivationPolicy::Accessory because the builder's on_tray_icon_event
            // closure is never called in that mode.
            app.on_tray_icon_event(|tray, event| {
                eprintln!("[irma] global tray event: {:?}", event);
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    eprintln!("[irma] tray left-click → popup menu");
                    let app = tray.app_handle();
                    if let Err(e) = tray::popup_tray_menu(app) {
                        eprintln!("[irma] popup_tray_menu failed: {e}");
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main" {
                    if let Some(state) = window.app_handle().try_state::<claude_pty::ClaudePty>() {
                        if let Ok(mut slot) = state.0.lock() {
                            if let Some(mut pty) = slot.take() {
                                let _ = pty.killer.kill();
                            }
                        }
                    }
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building Irma");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // Kill the backend process on exit.
            if let Some(backend) = app_handle.try_state::<BackendProcess>() {
                if let Ok(mut slot) = backend.0.lock() {
                    if let Some(mut child) = slot.take() {
                        eprintln!("[irma] killing backend (pid {})", child.id());
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
    });
}
