//! Window positioning and lifecycle wiring for the Irma shell.
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
const DEFAULT_DOG_Y_OFFSET: f64 = 28.0;
const DEFAULT_DOCK_WIDTH: f64 = 450.0;
/// Dock tile layout factors, used to reconstruct the Dock's pixel width from
/// `com.apple.dock` preferences (mirrors the approach used by lil-agents).
const DEFAULT_DOCK_TILESIZE: f64 = 48.0;
const DOCK_TILE_SLOT_FACTOR: f64 = 1.25;
const DOCK_DIVIDER_WIDTH: f64 = 12.0;
const DOCK_EDGE_FUDGE: f64 = 1.15;
const MAIN_VISIBILITY_EVENT: &str = "main:visibility";
/// Vertical lift (logical px) above the screen's bottom edge when she's beside
/// the Dock — sits her slightly off the floor rather than flush.
const BESIDE_DOCK_LIFT: f64 = 28.0;

fn env_f64(key: &str, default: f64) -> f64 {
    std::env::var(key)
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(default)
}

fn dock_clearance() -> f64 {
    env_f64("IRMA_DOCK_CLEARANCE", DEFAULT_DOCK_CLEARANCE)
}

/// Extra pixels to add to the computed `y`. Positive shifts the window
/// DOWN on screen — useful when the source sprite has empty padding below
/// the dog's feet so visually the dog ends up flush with the Dock.
fn dog_y_offset() -> f64 {
    env_f64("IRMA_DOG_Y_OFFSET", DEFAULT_DOG_Y_OFFSET)
}

/// Width (logical px) of the centred Dock footprint, used to size the walking
/// strip and to locate the Dock's left edge for "beside the Dock" mode.
///
/// Resolution order: an explicit `IRMA_DOCK_WIDTH` env var wins (`0` ⇒ no strip,
/// i.e. roam the full monitor width); otherwise the width is measured live from
/// the Dock's own preferences; failing that, `DEFAULT_DOCK_WIDTH`.
fn dock_width() -> Option<f64> {
    if let Ok(raw) = std::env::var("IRMA_DOCK_WIDTH") {
        if let Ok(val) = raw.parse::<f64>() {
            return if val > 0.0 { Some(val) } else { None };
        }
    }
    Some(measured_dock_width().unwrap_or(DEFAULT_DOCK_WIDTH))
}

/// Read a single scalar value from the `com.apple.dock` preferences domain via
/// `defaults`. Returns None if the key is unset or unreadable.
fn dock_default(key: &str) -> Option<String> {
    let out = std::process::Command::new("/usr/bin/defaults")
        .args(["read", "com.apple.dock", key])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let value = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

/// Count the elements of an array-valued `com.apple.dock` preference. Each Dock
/// tile is one dictionary carrying a `GUID` entry, so we count those lines.
fn dock_array_count(key: &str) -> usize {
    let Some(out) = std::process::Command::new("/usr/bin/defaults")
        .args(["read", "com.apple.dock", key])
        .output()
        .ok()
    else {
        return 0;
    };
    if !out.status.success() {
        return 0;
    }
    String::from_utf8_lossy(&out.stdout)
        .lines()
        .filter(|line| line.trim_start().starts_with("GUID ="))
        .count()
}

/// Best-effort Dock width (logical px), reconstructed from the Dock's own
/// preferences the same way the Dock lays its tiles out: tile size × icon count
/// + a divider between each populated group, plus a small edge-padding fudge.
/// Port of lil-agents' `getDockIconArea`. Returns None only if the layout works
/// out to zero tiles (the fallback below normally prevents that).
fn measured_dock_width() -> Option<f64> {
    let tile_size = dock_default("tilesize")
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(DEFAULT_DOCK_TILESIZE);
    let slot = tile_size * DOCK_TILE_SLOT_FACTOR;

    let mut persistent_apps = dock_array_count("persistent-apps");
    let mut persistent_others = dock_array_count("persistent-others");
    // Fallback when prefs can't be read (sandbox / empty Dock): assume a
    // typical Dock so we still produce a sane width.
    if persistent_apps == 0 && persistent_others == 0 {
        persistent_apps = 5;
        persistent_others = 3;
    }

    let show_recents = dock_default("show-recents")
        .map(|s| s == "1")
        .unwrap_or(true);
    let recent_apps = if show_recents {
        dock_array_count("recent-apps")
    } else {
        0
    };

    let total_icons = persistent_apps + persistent_others + recent_apps;
    if total_icons == 0 {
        return None;
    }

    let mut dividers = 0usize;
    if persistent_apps > 0 && (persistent_others > 0 || recent_apps > 0) {
        dividers += 1;
    }
    if persistent_others > 0 && recent_apps > 0 {
        dividers += 1;
    }
    if show_recents && recent_apps > 0 {
        dividers += 1;
    }

    let width = slot * total_icons as f64 + dividers as f64 * DOCK_DIVIDER_WIDTH;
    Some(width * DOCK_EDGE_FUDGE)
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
///   1. `IRMA_MONITOR_INDEX=<n>` selects the n-th available monitor (0-indexed).
///   2. The primary monitor (System Settings → Displays → "Use as main display").
///   3. The monitor under the cursor (last-resort fallback).
///
/// We intentionally do NOT chase the cursor monitor by default — the dog
/// staying on a stable screen is more important than reacting to brief
/// mouse moves to another display.
fn target_monitor(window: &WebviewWindow) -> tauri::Result<Option<Monitor>> {
    if let Ok(idx_s) = std::env::var("IRMA_MONITOR_INDEX") {
        if let Ok(idx) = idx_s.parse::<usize>() {
            let monitors = window.available_monitors()?;
            if let Some(m) = monitors.into_iter().nth(idx) {
                return Ok(Some(m));
            }
        }
    }
    if let Some(m) = window.primary_monitor()? {
        return Ok(Some(m));
    }
    cursor_monitor(window)
}

fn compute_bounds(
    window: &WebviewWindow,
    beside_dock: bool,
) -> tauri::Result<Option<CompanionBounds>> {
    let Some(monitor) = target_monitor(window)? else {
        return Ok(None);
    };
    let scale = monitor.scale_factor();
    let area = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    let win_size = window.outer_size()?.to_logical::<f64>(scale);
    // Beside the Dock there's nothing below her, so replace the Dock clearance
    // with a small lift so she sits just above the screen's bottom edge.
    let clearance = if beside_dock { BESIDE_DOCK_LIFT } else { dock_clearance() };
    let y_offset = dog_y_offset();
    let y = origin.y + area.height - win_size.height - clearance + y_offset;

    // Horizontal walking strip.
    let monitor_left = origin.x;
    let monitor_right = origin.x + area.width;
    let (strip_left, strip_right) = if beside_dock {
        // Beside the Dock: roam the bottom-left, from the screen's left edge
        // (x=0) up to where the centred Dock begins. macOS exposes no public
        // API for the Dock's width, so use IRMA_DOCK_WIDTH as the estimated
        // Dock footprint (default DEFAULT_DOCK_WIDTH).
        let dock_w = dock_width().unwrap_or(DEFAULT_DOCK_WIDTH);
        let dock_left = origin.x + area.width / 2.0 - dock_w / 2.0 - 20.0;
        (monitor_left, dock_left)
    } else {
        // In front of the Dock: a centred strip (IRMA_DOCK_WIDTH wide), or the
        // full monitor width when IRMA_DOCK_WIDTH=0.
        match dock_width() {
            Some(dw) => {
                let center = origin.x + area.width / 2.0;
                (center - dw / 2.0, center + dw / 2.0)
            }
            None => (origin.x, origin.x + area.width),
        }
    };
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
    let Some(bounds) = compute_bounds(window, false)? else {
        eprintln!("[irma] place_companion: no monitor available");
        return Ok(());
    };
    // Default anchor: a little in from the left edge of the primary monitor.
    // JS will move it elsewhere once it has bounds.
    let x = bounds.min_x + MARGIN_X;
    eprintln!(
        "[irma] place_companion: monitor=({:.0}x{:.0}) sprite=({:.0}x{:.0}) \
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
    /// Current IRMA_DOCK_CLEARANCE used to compute `y`.
    pub dock_clearance: f64,
    /// Current IRMA_DOG_Y_OFFSET added to `y`.
    pub dog_y_offset: f64,
}

fn emit_main_visibility(app: &AppHandle, visible: bool) {
    if let Err(err) = app.emit(MAIN_VISIBILITY_EVENT, visible) {
        eprintln!("[irma] emit {MAIN_VISIBILITY_EVENT} failed: {err}");
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
pub fn get_companion_bounds(
    window: WebviewWindow,
    beside_dock: bool,
) -> Result<CompanionBounds, String> {
    compute_bounds(&window, beside_dock)
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
            match event {
                WindowEvent::CloseRequested { api, .. } => {
                    api.prevent_close();
                    let _ = main_clone.hide();
                    emit_main_visibility(&app_handle, false);
                }
                WindowEvent::Focused(false) => {
                    let _ = main_clone.hide();
                    emit_main_visibility(&app_handle, false);
                }
                _ => {}
            }
        });
    }

    Ok(())
}
