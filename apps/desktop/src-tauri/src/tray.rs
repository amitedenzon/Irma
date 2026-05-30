//! Menu-bar tray icon — the only persistent app surface besides the sprite.
//!
//! Left-click on the icon toggles the main window; the menu provides
//! Toggle Irma / Placement options / Settings / Quit.

use tauri::{
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
    tray::TrayIconBuilder,
    AppHandle, Emitter, Manager,
};

use crate::windows;

fn build_tray_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let toggle = MenuItem::with_id(app, "toggle", "Toggle Irma", true, None::<&str>)?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let beside = CheckMenuItem::with_id(
        app,
        "companion_beside_dock",
        "Beside the Dock",
        true,
        true,
        None::<&str>,
    )?;
    let on_dock = CheckMenuItem::with_id(
        app,
        "companion_on_dock",
        "On the Dock",
        true,
        false,
        None::<&str>,
    )?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    Menu::with_items(app, &[&toggle, &sep1, &beside, &on_dock, &sep2, &settings, &quit])
}

/// Called from the global tray event listener in lib.rs to show the tray menu.
pub fn popup_tray_menu(app: &AppHandle) -> tauri::Result<()> {
    let menu = build_tray_menu(app)?;
    if let Some(window) = app.get_webview_window("companion") {
        window.popup_menu(&menu)?;
    }
    Ok(())
}

/// Show a native popup context menu on the companion window with placement options.
pub fn show_companion_menu(app: &AppHandle, beside_dock: bool) -> tauri::Result<()> {
    let beside = CheckMenuItem::with_id(
        app,
        "companion_beside_dock",
        "Beside the Dock",
        true,
        beside_dock,
        None::<&str>,
    )?;
    let on_dock = CheckMenuItem::with_id(
        app,
        "companion_on_dock",
        "On the Dock",
        true,
        !beside_dock,
        None::<&str>,
    )?;
    let menu = Menu::with_items(app, &[&beside, &on_dock])?;
    if let Some(window) = app.get_webview_window("companion") {
        let _ = window.popup_menu(&menu);
    }
    Ok(())
}

pub fn init(app: &AppHandle) -> tauri::Result<()> {
    let menu = build_tray_menu(app)?;
    let icon = app
        .default_window_icon()
        .expect("default window icon present (provided by tauri.conf.json bundle)")
        .clone();

    let _tray = TrayIconBuilder::with_id("irma-tray")
        .icon(icon)
        .icon_as_template(false)
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            eprintln!("[irma] tray menu event: {}", event.id().as_ref());
            match event.id().as_ref() {
                "toggle" => {
                    if let Err(err) = windows::toggle_main_internal(app) {
                        eprintln!("[irma] toggle_main_internal failed: {err}");
                    }
                }
                "companion_beside_dock" => {
                    let _ = app.emit("companion:placement", "beside-dock");
                }
                "companion_on_dock" => {
                    let _ = app.emit("companion:placement", "on-dock");
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
        .build(app)?;

    Ok(())
}
