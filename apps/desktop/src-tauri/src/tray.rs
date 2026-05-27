//! Menu-bar tray icon — the only persistent app surface besides the sprite.
//!
//! Left-click on the icon toggles the main window; the menu provides
//! Toggle Nofari / Settings / Quit.

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager,
};

use crate::windows;

pub fn init(app: &AppHandle) -> tauri::Result<()> {
    let toggle = MenuItem::with_id(app, "toggle", "Toggle Nofari", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&toggle, &settings, &quit])?;

    let icon = app
        .default_window_icon()
        .expect("default window icon present (provided by tauri.conf.json bundle)")
        .clone();

    let _tray = TrayIconBuilder::with_id("nofari-tray")
        .icon(icon)
        .icon_as_template(true)
        .menu(&menu)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "toggle" => {
                let _ = windows::toggle_main_internal(app);
            }
            "settings" => {
                windows::show_main(app);
            }
            "quit" => {
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let _ = windows::toggle_main_internal(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}
