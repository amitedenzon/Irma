mod claude_pty;
mod tray;
mod windows;

use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconEvent},
    Emitter, Manager,
};

/// Open a folder picker dialog, briefly activating the app so macOS allows it.
/// Uses a oneshot channel so the async command waits without blocking the runtime.
#[tauri::command]
async fn browse_folder(app: tauri::AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(tauri::ActivationPolicy::Regular);

    let (tx, rx) = std::sync::mpsc::channel();
    app.dialog().file().pick_folder(move |path| {
        let _ = tx.send(path);
    });
    let result = rx.recv().map_err(|e| e.to_string())?;

    #[cfg(target_os = "macos")]
    let _ = app.set_activation_policy(tauri::ActivationPolicy::Accessory);

    Ok(result.map(|p| p.to_string()))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .manage(claude_pty::ClaudePty::default())
        .invoke_handler(tauri::generate_handler![
            windows::position_companion,
            windows::toggle_main,
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

            // Handle companion context-menu placement selections.
            app.on_menu_event(|app, event| {
                match event.id().as_ref() {
                    "companion_beside_dock" => {
                        let _ = app.emit("companion:placement", "beside-dock");
                    }
                    "companion_on_dock" => {
                        let _ = app.emit("companion:placement", "on-dock");
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
        .run(tauri::generate_context!())
        .expect("error while running Irma");
}
