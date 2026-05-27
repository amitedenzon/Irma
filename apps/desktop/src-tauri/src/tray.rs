//! Menu-bar tray icon — the only persistent app surface besides the sprite.
//!
//! Left-click on the icon toggles the main window; the menu provides
//! Toggle Nofari / Settings / Quit.

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle,
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
        // Default in v2: left-click shows the menu when one is attached.
        // We want left-click → toggle main; right-click → menu.
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            eprintln!("[nofari] tray menu event: {}", event.id().as_ref());
            match event.id().as_ref() {
                "toggle" => {
                    if let Err(err) = windows::toggle_main_internal(app) {
                        eprintln!("[nofari] toggle_main_internal failed: {err}");
                    }
                }
                "settings" => {
                    windows::show_main(app);
                }
                "quit" => {
                    app.exit(0);
                }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                eprintln!("[nofari] tray left-click → toggle_main");
                if let Err(err) = windows::toggle_main_internal(tray.app_handle()) {
                    eprintln!("[nofari] toggle_main_internal failed: {err}");
                }
            }
        })
        .build(app)?;

    Ok(())
}
