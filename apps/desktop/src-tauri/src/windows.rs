//! Window positioning and lifecycle wiring for the Nofari shell.
//!
//! The companion window is sized to the sprite bounding box and pinned beside
//! the macOS Dock on the primary monitor (the one with the menu bar). JS owns
//! the dog's x/y inside that strip via `set_companion_pos`; Rust only handles
//! initial placement and reanchoring on scale-factor changes.

use serde::Serialize;
use tauri::{
    App, AppHandle, Emitter, LogicalPosition, Manager, Monitor, WebviewWindow, WindowEvent,
};

const MARGIN_X: f64 = 12.0;
const DEFAULT_DOCK_CLEARANCE: f64 = 80.0;
const DEFAULT_DOG_Y_OFFSET: f64 = 0.0;
const DEFAULT_DOCK_WIDTH: f64 = 490.0;
const MAIN_VISIBILITY_EVENT: &str = "main:visibility";

fn env_f64(key: &str, default: f64) -> f64 {
    std::env::var(key)
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(default)
}

fn dock_clearance() -> f64 {
    env_f64("NOFARI_DOCK_CLEARANCE", DEFAULT_DOCK_CLEARANCE)
}

/// Extra pixels to add to the computed `y`. Positive shifts the window
/// DOWN on screen — useful when the source sprite has empty padding below
/// the dog's feet so visually the dog ends up flush with the Dock.
fn dog_y_offset() -> f64 {
    env_f64("NOFARI_DOG_Y_OFFSET", DEFAULT_DOG_Y_OFFSET)
}

/// Width (logical px) of the horizontal walking strip, centered on the
/// monitor. Defaults to 490 — calibrated for a typical macOS Dock. Set
/// `NOFARI_DOCK_WIDTH=0` to allow the dog to walk the entire monitor width.
fn dock_width() -> Option<f64> {
    let val = std::env::var("NOFARI_DOCK_WIDTH")
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(DEFAULT_DOCK_WIDTH);
    if val > 0.0 {
        Some(val)
    } else {
        None
    }
}

/// Pick the monitor that contains the system cursor, so the dog follows
/// whichever screen the user is working on (where the macOS Dock currently
/// lives by default).
fn cursor_monitor(window: &WebviewWindow) -> tauri::Result<Option<Monitor>> {
    let Ok(cursor) = window.cursor_position() else {
        return Ok(None);
    };
    let monitors = window.available_monitors()?;
    for m in monitors {
        let pos = m.position();
        let size = m.size();
        let x0 = pos.x as f64;
        let y0 = pos.y as f64;
        let x1 = x0 + size.width as f64;
        let y1 = y0 + size.height as f64;
        if cursor.x >= x0 && cursor.x < x1 && cursor.y >= y0 && cursor.y < y1 {
            return Ok(Some(m));
        }
    }
    Ok(None)
}

/// Pick the monitor the companion should live on. Preference order:
///   1. The monitor under the cursor (the active screen, where the macOS
///      Dock currently is by default).
///   2. The primary monitor (menu-bar screen).
///   3. The window's current monitor (fallback for headless cases).
fn target_monitor(window: &WebviewWindow) -> tauri::Result<Option<Monitor>> {
    if let Some(m) = cursor_monitor(window)? {
        return Ok(Some(m));
    }
    if let Some(m) = window.primary_monitor()? {
        return Ok(Some(m));
    }
    window.current_monitor()
}

fn compute_bounds(window: &WebviewWindow) -> tauri::Result<Option<CompanionBounds>> {
    let Some(monitor) = target_monitor(window)? else {
        return Ok(None);
    };
    let scale = monitor.scale_factor();
    let area = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    let win_size = window.outer_size()?.to_logical::<f64>(scale);
    let clearance = dock_clearance();
    let y_offset = dog_y_offset();
    let y = origin.y + area.height - win_size.height - clearance + y_offset;

    // Horizontal walking strip. If NOFARI_DOCK_WIDTH is set, center a strip of
    // that width on the monitor; otherwise allow the full width.
    let (strip_left, strip_right) = match dock_width() {
        Some(dw) => {
            let center = origin.x + area.width / 2.0;
            (center - dw / 2.0, center + dw / 2.0)
        }
        None => (origin.x, origin.x + area.width),
    };
    let monitor_left = origin.x;
    let monitor_right = origin.x + area.width;
    let strip_left = strip_left.max(monitor_left);
    let strip_right = strip_right.min(monitor_right);
    let min_x = strip_left;
    let max_x = (strip_right - win_size.width).max(strip_left);

    Ok(Some(CompanionBounds {
        monitor_width: area.width,
        monitor_height: area.height,
        sprite_width: win_size.width,
        sprite_height: win_size.height,
        y,
        min_x,
        max_x,
        dock_clearance: clearance,
        dog_y_offset: y_offset,
    }))
}

fn place_companion(window: &WebviewWindow) -> tauri::Result<()> {
    let Some(bounds) = compute_bounds(window)? else {
        eprintln!("[nofari] place_companion: no monitor available");
        return Ok(());
    };
    // Default anchor: a little in from the left edge of the primary monitor.
    // JS will move it elsewhere once it has bounds.
    let x = bounds.min_x + MARGIN_X;
    eprintln!(
        "[nofari] place_companion: monitor=({:.0}x{:.0}) sprite=({:.0}x{:.0}) \
         strip=[{:.0},{:.0}] → set_position=({:.1},{:.1}) \
         (dock_clearance={}, dog_y_offset={})",
        bounds.monitor_width,
        bounds.monitor_height,
        bounds.sprite_width,
        bounds.sprite_height,
        bounds.min_x,
        bounds.max_x,
        x,
        bounds.y,
        bounds.dock_clearance,
        bounds.dog_y_offset,
    );
    window.set_position(LogicalPosition::new(x, bounds.y))?;
    Ok(())
}

#[derive(Serialize, Clone, Copy)]
#[serde(rename_all = "camelCase")]
pub struct CompanionBounds {
    pub monitor_width: f64,
    pub monitor_height: f64,
    pub sprite_width: f64,
    pub sprite_height: f64,
    /// Top y for the companion such that its bottom sits at the dock's top.
    pub y: f64,
    /// Leftmost valid x (window top-left).
    pub min_x: f64,
    /// Rightmost valid x (window top-left). min_x + monitor_width - sprite_width.
    pub max_x: f64,
    /// Current NOFARI_DOCK_CLEARANCE used to compute `y`.
    pub dock_clearance: f64,
    /// Current NOFARI_DOG_Y_OFFSET added to `y`.
    pub dog_y_offset: f64,
}

fn emit_main_visibility(app: &AppHandle, visible: bool) {
    if let Err(err) = app.emit(MAIN_VISIBILITY_EVENT, visible) {
        eprintln!("[nofari] emit {MAIN_VISIBILITY_EVENT} failed: {err}");
    }
}

pub fn toggle_main_internal(app: &AppHandle) -> tauri::Result<()> {
    let Some(win) = app.get_webview_window("main") else {
        return Ok(());
    };
    if win.is_visible()? {
        win.hide()?;
        emit_main_visibility(app, false);
    } else {
        win.show()?;
        win.set_focus()?;
        emit_main_visibility(app, true);
    }
    Ok(())
}

pub fn show_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.set_focus();
        emit_main_visibility(app, true);
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

#[tauri::command]
pub fn get_companion_bounds(window: WebviewWindow) -> Result<CompanionBounds, String> {
    compute_bounds(&window)
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "no monitor available".to_string())
}

#[tauri::command]
pub fn set_companion_pos(window: WebviewWindow, x: f64, y: f64) -> Result<(), String> {
    window
        .set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())
}

/// Wire window-event listeners on both windows. Called once during setup.
///
/// IMPORTANT: we deliberately do NOT re-anchor the companion on
/// `WindowEvent::Moved` — JS drives the dog's position via `set_companion_pos`
/// and reanchoring on every move would fight the walk animation. We do
/// reanchor on `ScaleFactorChanged` because a scale change can shift the
/// effective dock clearance.
pub fn wire_windows(app: &mut App) -> tauri::Result<()> {
    if let Some(companion) = app.get_webview_window("companion") {
        place_companion(&companion)?;
        let companion_clone = companion.clone();
        companion.on_window_event(move |event| {
            if matches!(event, WindowEvent::ScaleFactorChanged { .. }) {
                let _ = place_companion(&companion_clone);
            }
        });
    }

    if let Some(main) = app.get_webview_window("main") {
        let main_clone = main.clone();
        let app_handle = app.handle().clone();
        main.on_window_event(move |event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = main_clone.hide();
                emit_main_visibility(&app_handle, false);
            }
        });
    }

    Ok(())
}
