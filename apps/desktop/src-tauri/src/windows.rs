//! Window positioning and lifecycle wiring for the Nofari shell.
//!
//! The companion window is sized to the sprite bounding box and pinned beside
//! the macOS Dock. The main window is hidden on launch and hidden — not
//! destroyed — on a user-issued close request, so re-opening it from the tray
//! or companion click is instant.

use tauri::{App, AppHandle, LogicalPosition, Manager, WebviewWindow, WindowEvent};

const SPRITE_H: f64 = 96.0;
const MARGIN_X: f64 = 12.0;
const DEFAULT_DOCK_CLEARANCE: f64 = 80.0;

fn dock_clearance() -> f64 {
    std::env::var("NOFARI_DOCK_CLEARANCE")
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(DEFAULT_DOCK_CLEARANCE)
}

fn place_companion(window: &WebviewWindow) -> tauri::Result<()> {
    let Some(monitor) = window.current_monitor()? else {
        eprintln!("[nofari] place_companion: current_monitor() returned None");
        return Ok(());
    };
    let scale = monitor.scale_factor();
    let area = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    let clearance = dock_clearance();
    let x = origin.x + MARGIN_X;
    let y = origin.y + area.height - SPRITE_H - clearance;
    eprintln!(
        "[nofari] place_companion: monitor=({:.0}x{:.0}@{:.0},{:.0}) scale={} \
         → set_position=({:.1},{:.1}) (dock_clearance={})",
        area.width, area.height, origin.x, origin.y, scale, x, y, clearance
    );
    window.set_position(LogicalPosition::new(x, y))?;
    Ok(())
}

pub fn toggle_main_internal(app: &AppHandle) -> tauri::Result<()> {
    let Some(win) = app.get_webview_window("main") else {
        return Ok(());
    };
    if win.is_visible()? {
        win.hide()?;
    } else {
        win.show()?;
        win.set_focus()?;
    }
    Ok(())
}

pub fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
    }
}

#[tauri::command]
pub fn position_companion(window: WebviewWindow) -> Result<(), String> {
    place_companion(&window).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn toggle_main(app: AppHandle) -> Result<(), String> {
    toggle_main_internal(&app).map_err(|e| e.to_string())
}

/// Wire window-event listeners on both windows. Called once during setup.
pub fn wire_windows(app: &mut App) -> tauri::Result<()> {
    if let Some(companion) = app.get_webview_window("companion") {
        place_companion(&companion)?;
        let companion_clone = companion.clone();
        companion.on_window_event(move |event| {
            if matches!(
                event,
                WindowEvent::ScaleFactorChanged { .. } | WindowEvent::Moved(_)
            ) {
                let _ = place_companion(&companion_clone);
            }
        });
    }

    if let Some(main) = app.get_webview_window("main") {
        let main_clone = main.clone();
        main.on_window_event(move |event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = main_clone.hide();
            }
        });
    }

    Ok(())
}
