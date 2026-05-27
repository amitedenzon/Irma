mod tray;
mod windows;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            windows::position_companion,
            windows::toggle_main,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            windows::wire_windows(app)?;
            tray::init(app.handle())?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Nofari");
}
