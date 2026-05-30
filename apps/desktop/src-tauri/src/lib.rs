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
