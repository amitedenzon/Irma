//! Window positioning and lifecycle wiring for the Irma shell.
//!
//! The companion window is sized to the sprite bounding box and pinned beside
//! the macOS Dock on the primary monitor (the one with the menu bar). JS owns
//! the dog's x/y inside that strip via `set_companion_pos`; Rust only handles
//! initial placement and reanchoring on scale-factor changes.

use std::sync::atomic::Ordering;

use serde::Serialize;
use tauri::{
    App, AppHandle, Emitter, LogicalPosition, Manager, Monitor, State, WebviewWindow, WindowEvent,
};

use crate::DialogOpen;

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

/// Inputs for the pure drop→zone decision. All x values are logical px in the
/// monitor's coordinate space. `dock_left`/`dock_right` are only meaningful when
/// `is_primary` (a secondary monitor has no Dock).
#[derive(Debug)]
pub struct ZoneInput {
    pub monitor_left: f64,
    pub monitor_right: f64,
    pub is_primary: bool,
    pub dock_left: f64,
    pub dock_right: f64,
}

/// Decide which zone a drop at `center_x` lands in. Pure (no window access) so
/// it can be unit-tested. `tie_left` resolves the measure-zero exact-center case
/// on a secondary monitor.
pub fn decide_drop_zone(center_x: f64, z: &ZoneInput, tie_left: bool) -> &'static str {
    if z.is_primary {
        // `center_x == dock_left` or `== dock_right` intentionally falls through to "on-dock":
        // the Dock edges already carry ±50 px padding, so an exact-boundary center is on-dock —
        // a deliberate measure-zero choice.
        if center_x < z.dock_left {
            "left-of-dock"
        } else if center_x > z.dock_right {
            "right-of-dock"
        } else {
            "on-dock"
        }
    } else {
        let mid = (z.monitor_left + z.monitor_right) / 2.0;
        if center_x < mid {
            "left-of-dock"
        } else if center_x > mid {
            "right-of-dock"
        } else if tie_left {
            "left-of-dock"
        } else {
            "right-of-dock"
        }
    }
}

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

/// Two monitors are "the same" if their names match (preferred) or, lacking
/// names, their physical origins coincide.
fn monitors_equal(a: &Monitor, b: &Monitor) -> bool {
    match (a.name(), b.name()) {
        (Some(na), Some(nb)) => na == nb,
        _ => a.position() == b.position(),
    }
}

fn is_primary_monitor(window: &WebviewWindow, monitor: &Monitor) -> tauri::Result<bool> {
    match window.primary_monitor()? {
        Some(primary) => Ok(monitors_equal(monitor, &primary)),
        None => Ok(true), // no primary info → single-screen assumption
    }
}

fn monitor_by_name(window: &WebviewWindow, name: &str) -> tauri::Result<Option<Monitor>> {
    for m in window.available_monitors()? {
        if m.name().map(|n| n.as_str()) == Some(name) {
            return Ok(Some(m));
        }
    }
    Ok(None)
}

/// Resolve the monitor the companion should use: a saved monitor by name wins,
/// otherwise fall back to `target_monitor` (env → primary → cursor).
fn resolve_monitor(
    window: &WebviewWindow,
    monitor_name: Option<&str>,
) -> tauri::Result<Option<Monitor>> {
    if let Some(name) = monitor_name {
        if let Some(m) = monitor_by_name(window, name)? {
            return Ok(Some(m));
        }
        eprintln!("[irma] resolve_monitor: saved monitor {name:?} not found; falling back to primary");
    }
    target_monitor(window)
}

/// The padded Dock edges (logical x) on the primary monitor: the left strip ends
/// at `.0` and the right strip begins at `.1`. The ±50 padding keeps the companion
/// clear of the centred Dock.
fn dock_zone_edges(origin_x: f64, area_width: f64, dock_w: f64) -> (f64, f64) {
    let center = origin_x + area_width / 2.0;
    (center - dock_w / 2.0 - 50.0, center + dock_w / 2.0 + 50.0)
}

fn compute_bounds_for(
    window: &WebviewWindow,
    monitor: &Monitor,
    dock_position: &str,
) -> tauri::Result<CompanionBounds> {
    let scale = monitor.scale_factor();
    // NOTE: bounds are computed in the target monitor's logical px. `set_position`
    // (via set_companion_pos) converts using the monitor the window currently sits
    // on, so callers must move the window onto `monitor` before/around applying
    // these bounds when monitors have different scale factors.
    let area = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    let win_size = window.outer_size()?.to_logical::<f64>(scale);
    // Left/right of dock have nothing below them, so use a small lift instead
    // of the full Dock clearance.
    let clearance = if dock_position == "on-dock" {
        dock_clearance()
    } else {
        BESIDE_DOCK_LIFT
    };
    let y_offset = dog_y_offset();
    let y = origin.y + area.height - win_size.height - clearance + y_offset;

    let monitor_left = origin.x;
    let monitor_right = origin.x + area.width;
    let is_primary = is_primary_monitor(window, monitor)?;

    let (strip_left, strip_right) = if is_primary {
        // Primary monitor hosts the Dock: zones are relative to the Dock footprint.
        match dock_position {
            "left-of-dock" => {
                let (dock_left, _) =
                    dock_zone_edges(origin.x, area.width, dock_width().unwrap_or(DEFAULT_DOCK_WIDTH));
                (monitor_left, dock_left)
            }
            "right-of-dock" => {
                let (_, dock_right) =
                    dock_zone_edges(origin.x, area.width, dock_width().unwrap_or(DEFAULT_DOCK_WIDTH));
                (dock_right, monitor_right)
            }
            _ => match dock_width() {
                Some(dw) => {
                    let center = origin.x + area.width / 2.0;
                    (center - dw / 2.0, center + dw / 2.0)
                }
                None => (monitor_left, monitor_right),
            },
        }
    } else {
        // Secondary monitor has no Dock: split at center into left/right halves.
        // `on-dock` should never be selected here; treat it defensively as the
        // left half.
        let center = origin.x + area.width / 2.0;
        match dock_position {
            "right-of-dock" => (center, monitor_right),
            _ => (monitor_left, center),
        }
    };
    let strip_left = strip_left.max(monitor_left);
    let strip_right = strip_right.min(monitor_right);
    let strip_right = strip_right.max(strip_left); // never invert the strip
    let min_x = strip_left;
    let max_x = (strip_right - win_size.width).max(strip_left);

    Ok(CompanionBounds {
        monitor_width: area.width,
        monitor_height: area.height,
        sprite_width: win_size.width,
        sprite_height: win_size.height,
        y,
        min_x,
        max_x,
        dock_clearance: clearance,
        dog_y_offset: y_offset,
    })
}

fn place_companion(window: &WebviewWindow) -> tauri::Result<()> {
    let Some(monitor) = target_monitor(window)? else {
        eprintln!("[irma] place_companion: no monitor available");
        return Ok(());
    };
    let bounds = compute_bounds_for(window, &monitor, "left-of-dock")?;
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

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct ResolvedDrop {
    /// Monitor the window landed on (empty string if the monitor is unnamed).
    pub monitor_name: String,
    /// Resolved zone: "left-of-dock" | "on-dock" | "right-of-dock".
    pub dock_position: String,
    /// Landing x (logical px, window top-left), clamped into the zone strip.
    pub x: f64,
    pub bounds: CompanionBounds,
}

/// Resolve where the companion should snap to, based on its current (post-drag)
/// window position. Reads the live window geometry so the result is correct even
/// if the live drag drifted under mixed DPI.
#[tauri::command]
pub fn resolve_companion_drop(window: WebviewWindow) -> Result<ResolvedDrop, String> {
    let pos = window.outer_position().map_err(|e| e.to_string())?;
    let size = window.outer_size().map_err(|e| e.to_string())?;
    let center_phys_x = pos.x as f64 + size.width as f64 / 2.0;
    let center_phys_y = pos.y as f64 + size.height as f64 / 2.0;

    // Monitor containing the window center; fall back to primary.
    let monitors = window.available_monitors().map_err(|e| e.to_string())?;
    let monitor = monitors
        .into_iter()
        .find(|m| {
            let mp = m.position();
            let ms = m.size();
            let x0 = mp.x as f64;
            let y0 = mp.y as f64;
            center_phys_x >= x0
                && center_phys_x < x0 + ms.width as f64
                && center_phys_y >= y0
                && center_phys_y < y0 + ms.height as f64
        })
        .or_else(|| window.primary_monitor().ok().flatten())
        .ok_or_else(|| "no monitor available".to_string())?;

    // NOTE: a cross-monitor drop to a different-DPI screen relies on macOS having
    // applied the scale change by the time this runs; in practice the scale update
    // lands in the same run-loop cycle as the window move, so reading the landed
    // monitor's scale here is correct.
    let scale = monitor.scale_factor();
    let area = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    let win_size = size.to_logical::<f64>(scale);
    let center_x = center_phys_x / scale;

    let is_primary = is_primary_monitor(&window, &monitor).map_err(|e| e.to_string())?;
    let (dock_left, dock_right) = if is_primary {
        dock_zone_edges(origin.x, area.width, dock_width().unwrap_or(DEFAULT_DOCK_WIDTH))
    } else {
        (0.0, 0.0)
    };
    let z = ZoneInput {
        monitor_left: origin.x,
        monitor_right: origin.x + area.width,
        is_primary,
        dock_left,
        dock_right,
    };
    // Deterministic tie-break for an exact-center secondary drop (measure-zero).
    let tie_left = (pos.x & 1) == 0;
    let zone = decide_drop_zone(center_x, &z, tie_left);

    let bounds = compute_bounds_for(&window, &monitor, zone).map_err(|e| e.to_string())?;
    let landing_x = (center_x - win_size.width / 2.0).clamp(bounds.min_x, bounds.max_x);
    let monitor_name = monitor.name().cloned().unwrap_or_default();

    Ok(ResolvedDrop {
        monitor_name,
        dock_position: zone.to_string(),
        x: landing_x,
        bounds,
    })
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
pub fn is_main_visible(app: AppHandle) -> bool {
    app.get_webview_window("main")
        .and_then(|w| w.is_visible().ok())
        .unwrap_or(false)
}

/// True while the main window is actually *presented to the user*: on-screen
/// AND the key (focused) window. `is_visible()` alone stays true when the user
/// switches to another app (the window is merely occluded, not hidden), which
/// would otherwise leave the companion stuck barking. The `DialogOpen` guard
/// keeps her "present" while our own native folder picker steals key focus, so
/// browsing for a folder doesn't break her out of bark mode.
#[tauri::command]
pub fn is_main_active(app: AppHandle, dialog_open: State<'_, DialogOpen>) -> bool {
    let Some(win) = app.get_webview_window("main") else {
        return false;
    };
    if !win.is_visible().unwrap_or(false) {
        return false;
    }
    if dialog_open.0.load(Ordering::Acquire) {
        return true;
    }
    win.is_focused().unwrap_or(false)
}

#[tauri::command]
pub fn get_companion_bounds(
    window: WebviewWindow,
    monitor_name: Option<String>,
    dock_position: String,
) -> Result<CompanionBounds, String> {
    let monitor = resolve_monitor(&window, monitor_name.as_deref())
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "no monitor available".to_string())?;
    compute_bounds_for(&window, &monitor, &dock_position).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn set_companion_pos(window: WebviewWindow, x: f64, y: f64) -> Result<(), String> {
    window
        .set_position(LogicalPosition::new(x, y))
        .map_err(|e| e.to_string())
}

/// Show a native context menu on the companion window with placement options.
/// `dock_position` reflects the current setting so the active item gets a checkmark.
#[tauri::command]
pub fn show_companion_context_menu(app: AppHandle, dock_position: String) -> Result<(), String> {
    crate::tray::show_companion_menu(&app, &dock_position).map_err(|e| e.to_string())
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
                    // Do not auto-hide on focus loss — native dialogs (folder picker,
                    // file input) all steal focus and would collapse the window.
                    // The window hides only via the sprite-click toggle or the tray.
                }
                _ => {}
            }
        });
    }

    Ok(())
}

#[cfg(test)]
mod zone_tests {
    use super::{decide_drop_zone, ZoneInput};

    fn primary(dock_left: f64, dock_right: f64) -> ZoneInput {
        ZoneInput {
            monitor_left: 0.0,
            monitor_right: 1440.0,
            is_primary: true,
            dock_left,
            dock_right,
        }
    }

    fn secondary() -> ZoneInput {
        ZoneInput {
            monitor_left: 1440.0,
            monitor_right: 2960.0,
            is_primary: false,
            dock_left: 0.0,  // unused on a secondary monitor (no Dock)
            dock_right: 0.0, // unused on a secondary monitor (no Dock)
        }
    }

    #[test]
    fn primary_picks_left_on_dock_right() {
        let z = primary(600.0, 840.0);
        assert_eq!(decide_drop_zone(100.0, &z, true), "left-of-dock");
        assert_eq!(decide_drop_zone(720.0, &z, true), "on-dock");
        assert_eq!(decide_drop_zone(1000.0, &z, true), "right-of-dock");
    }

    #[test]
    fn secondary_splits_at_center() {
        let z = secondary();
        assert_eq!(decide_drop_zone(1500.0, &z, true), "left-of-dock");
        assert_eq!(decide_drop_zone(2900.0, &z, true), "right-of-dock");
    }

    #[test]
    fn secondary_never_returns_on_dock() {
        let z = secondary();
        let mid = (z.monitor_left + z.monitor_right) / 2.0;
        assert_eq!(decide_drop_zone(mid, &z, true), "left-of-dock");
        assert_eq!(decide_drop_zone(mid, &z, false), "right-of-dock");
        assert_ne!(decide_drop_zone(1500.0, &z, true), "on-dock");
    }
}
