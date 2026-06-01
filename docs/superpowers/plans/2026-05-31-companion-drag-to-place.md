# Companion Drag-to-Place Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the companion's right-click/tray placement menu with direct drag-and-drop — free X/Y drag across monitors, snap-to-zone on release, persisted placement, and a "Reset Position" menu item.

**Architecture:** During drag, the React companion view repositions the OS window to chase the cursor (so pointer events keep firing) and suspends the autonomous "dog brain." On release, Rust reads the window's real position and resolves `{ monitor, zone, landing-x, bounds }`; the frontend applies it, persists it, and re-bootstraps roaming. The three existing zones (`left-of-dock` / `on-dock` / `right-of-dock`) are unchanged — drag merely *selects* one. Secondary monitors expose only left/right halves (no Dock there).

**Tech Stack:** Tauri v2 (Rust), React 19 + TypeScript, Vite. Rust geometry is unit-tested with `cargo test`; the IPC/DOM-bound frontend is type-checked (`npm run typecheck`) and manually verified (no frontend test runner exists in this repo).

**Branch:** `feat/companion-drag-to-place` (already created; the spec commit is its first commit).

---

## File structure

| File | Responsibility | Change |
|---|---|---|
| `apps/desktop/src-tauri/src/windows.rs` | Window geometry, zone strips, drop resolution, drag/bounds commands | Modify |
| `apps/desktop/src-tauri/src/tray.rs` | Tray + companion context menu | Modify |
| `apps/desktop/src-tauri/src/lib.rs` | Command registration + menu-event routing | Modify |
| `apps/desktop/src/lib/settings.ts` | Persisted settings (+ `monitorName`) | Modify |
| `apps/desktop/src/companion/Companion.tsx` | Sprite render, dog brain, drag handlers | Modify |

**Out of scope (do not touch):** `src/main/settings/SettingsView.tsx` keeps its Dock-zone selector (calls `saveDockPosition`, which leaves `monitorName` untouched — a harmless secondary control). No backend/SSE/brief changes.

---

## Task 1: Pure zone-decision helper + Rust unit tests (TDD)

Extract the drop→zone decision into a pure function so it's unit-testable without a live window.

**Files:**
- Modify: `apps/desktop/src-tauri/src/windows.rs` (add struct, fn, and a `#[cfg(test)]` module)

- [ ] **Step 1: Write the failing tests**

Append this module at the end of `apps/desktop/src-tauri/src/windows.rs`:

```rust
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
            dock_left: 0.0,
            dock_right: 0.0,
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
```

- [ ] **Step 2: Run tests to verify they fail to compile**

Run: `cd apps/desktop/src-tauri && cargo test zone_tests`
Expected: FAIL — `cannot find type ZoneInput` / `cannot find function decide_drop_zone`.

- [ ] **Step 3: Implement the helper**

Add near the top of `windows.rs`, just below the `const` block (after line ~30):

```rust
/// Inputs for the pure drop→zone decision. All x values are logical px in the
/// monitor's coordinate space. `dock_left`/`dock_right` are only meaningful when
/// `is_primary` (a secondary monitor has no Dock).
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/desktop/src-tauri && cargo test zone_tests`
Expected: PASS — `test result: ok. 3 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src-tauri/src/windows.rs
git commit -m "feat(companion): pure drop-zone decision + unit tests"
```

---

## Task 2: Monitor-aware bounds (`compute_bounds_for` + resolvers)

Make bounds computation accept an explicit monitor and support secondary-screen halves. This unlocks living on a non-primary monitor.

**Files:**
- Modify: `apps/desktop/src-tauri/src/windows.rs`

- [ ] **Step 1: Add monitor-identity + resolver helpers**

Add these functions to `windows.rs` (e.g. just above `compute_bounds`):

```rust
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
    }
    target_monitor(window)
}
```

- [ ] **Step 2: Replace `compute_bounds` with `compute_bounds_for`**

Replace the entire existing `compute_bounds` function (currently `windows.rs:196-257`) with:

```rust
fn compute_bounds_for(
    window: &WebviewWindow,
    monitor: &Monitor,
    dock_position: &str,
) -> tauri::Result<CompanionBounds> {
    let scale = monitor.scale_factor();
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
                let dock_w = dock_width().unwrap_or(DEFAULT_DOCK_WIDTH);
                let dock_left = origin.x + area.width / 2.0 - dock_w / 2.0 - 50.0;
                (monitor_left, dock_left)
            }
            "right-of-dock" => {
                let dock_w = dock_width().unwrap_or(DEFAULT_DOCK_WIDTH);
                let dock_right = origin.x + area.width / 2.0 + dock_w / 2.0 + 50.0;
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
```

- [ ] **Step 3: Update `place_companion` to use the new signature**

Replace the body of `place_companion` (currently `windows.rs:259-284`) with:

```rust
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
```

- [ ] **Step 4: Update `get_companion_bounds` to accept `monitor_name`**

Replace the existing `get_companion_bounds` command (currently `windows.rs:371-379`) with:

```rust
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
```

- [ ] **Step 5: Verify it compiles and tests still pass**

Run: `cd apps/desktop/src-tauri && cargo test zone_tests && cargo build`
Expected: tests PASS; build succeeds (warnings about the now-unused `compute_bounds` name are fine only if any remain — there should be none since it was replaced).

- [ ] **Step 6: Commit**

```bash
git add apps/desktop/src-tauri/src/windows.rs
git commit -m "feat(companion): monitor-aware compute_bounds_for + secondary halves"
```

---

## Task 3: `resolve_companion_drop` command

Add the command the frontend calls on release. It reads the window's real position and returns the resolved placement.

**Files:**
- Modify: `apps/desktop/src-tauri/src/windows.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs` (register the command)

- [ ] **Step 1: Add the `ResolvedDrop` struct + command**

Add to `windows.rs` (e.g. just after the `CompanionBounds` struct definition):

```rust
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
        .or(window.primary_monitor().map_err(|e| e.to_string())?)
        .ok_or_else(|| "no monitor available".to_string())?;

    let scale = monitor.scale_factor();
    let area = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    let win_size = size.to_logical::<f64>(scale);
    let center_x = center_phys_x / scale;

    let is_primary = is_primary_monitor(&window, &monitor).map_err(|e| e.to_string())?;
    let (dock_left, dock_right) = if is_primary {
        let dock_w = dock_width().unwrap_or(DEFAULT_DOCK_WIDTH);
        let c = origin.x + area.width / 2.0;
        (c - dock_w / 2.0 - 50.0, c + dock_w / 2.0 + 50.0)
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
```

- [ ] **Step 2: Register the command in `lib.rs`**

In `apps/desktop/src-tauri/src/lib.rs`, inside the `tauri::generate_handler![ ... ]` list (currently `lib.rs:128-141`), add `windows::resolve_companion_drop,` after `windows::set_companion_pos,`:

```rust
            windows::get_companion_bounds,
            windows::set_companion_pos,
            windows::resolve_companion_drop,
            windows::show_companion_context_menu,
```

- [ ] **Step 3: Verify it compiles**

Run: `cd apps/desktop/src-tauri && cargo build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add apps/desktop/src-tauri/src/windows.rs apps/desktop/src-tauri/src/lib.rs
git commit -m "feat(companion): resolve_companion_drop command"
```

---

## Task 4: Replace placement menu with "Reset Position"

Swap the three-zone tray/context menu items for a single reset item that emits `companion:reset-position`.

**Files:**
- Modify: `apps/desktop/src-tauri/src/tray.rs`
- Modify: `apps/desktop/src-tauri/src/lib.rs`
- Modify: `apps/desktop/src-tauri/src/windows.rs` (`show_companion_context_menu` signature)

- [ ] **Step 1: Update the tray menu imports + builder**

In `tray.rs`, change the menu import (line 7) from:

```rust
    menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem},
```
to:
```rust
    menu::{Menu, MenuItem, PredefinedMenuItem},
```

Replace `build_tray_menu` (currently `tray.rs:14-45`) with:

```rust
fn build_tray_menu(app: &AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let toggle = MenuItem::with_id(app, "toggle", "Toggle Irma", true, None::<&str>)?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let reset = MenuItem::with_id(app, "reset_position", "Reset Position", true, None::<&str>)?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let settings = MenuItem::with_id(app, "settings", "Settings", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    Menu::with_items(app, &[&toggle, &sep1, &reset, &sep2, &settings, &quit])
}
```

- [ ] **Step 2: Update `show_companion_menu`**

Replace `show_companion_menu` (currently `tray.rs:56-87`) with (note: no more `dock_position` param):

```rust
/// Show a native popup context menu on the companion window with a reset action.
pub fn show_companion_menu(app: &AppHandle) -> tauri::Result<()> {
    let reset = MenuItem::with_id(app, "reset_position", "Reset Position", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&reset])?;
    if let Some(window) = app.get_webview_window("companion") {
        let _ = window.popup_menu(&menu);
    }
    Ok(())
}
```

- [ ] **Step 3: Update the tray builder's menu-event arm**

In `tray.rs`, in the `.on_menu_event` closure (currently `tray.rs:103-125`), replace the three `companion_*_of_dock` arms with a single arm. The block becomes:

```rust
            match event.id().as_ref() {
                "toggle" => {
                    if let Err(err) = windows::toggle_main_internal(app) {
                        eprintln!("[irma] toggle_main_internal failed: {err}");
                    }
                }
                "reset_position" => {
                    let _ = app.emit("companion:reset-position", ());
                }
                "settings" => {
                    windows::show_main(app);
                }
                "quit" => {
                    app.exit(0);
                }
                _ => {}
            }
```

- [ ] **Step 4: Update the app-level menu-event handler in `lib.rs`**

In `lib.rs`, replace the `app.on_menu_event` block (currently `lib.rs:152-165`) with:

```rust
            // Handle companion context-menu actions.
            app.on_menu_event(|app, event| {
                if event.id().as_ref() == "reset_position" {
                    let _ = app.emit("companion:reset-position", ());
                }
            });
```

- [ ] **Step 5: Update `show_companion_context_menu` in `windows.rs`**

Replace the command (currently `windows.rs:390-393`) with (drops the `dock_position` arg):

```rust
/// Show a native context menu on the companion window with a reset action.
#[tauri::command]
pub fn show_companion_context_menu(app: AppHandle) -> Result<(), String> {
    crate::tray::show_companion_menu(&app).map_err(|e| e.to_string())
}
```

- [ ] **Step 6: Verify it compiles**

Run: `cd apps/desktop/src-tauri && cargo build`
Expected: build succeeds (no unused-import warning for `CheckMenuItem`).

- [ ] **Step 7: Commit**

```bash
git add apps/desktop/src-tauri/src/tray.rs apps/desktop/src-tauri/src/lib.rs apps/desktop/src-tauri/src/windows.rs
git commit -m "feat(companion): replace placement menu with Reset Position"
```

---

## Task 5: Persist `monitorName` in settings

Extend the settings module so placement (monitor + zone) round-trips through `localStorage`.

**Files:**
- Modify: `apps/desktop/src/lib/settings.ts`

- [ ] **Step 1: Add the monitor key + type field**

In `settings.ts`, add the field to `IrmaSettings` (currently lines 29-32):

```ts
export interface IrmaSettings {
  companionId: string;
  dockPosition: DockPosition;
  monitorName: string | null;
}
```

Add the storage key next to the existing ones (after line 35):

```ts
const MONITOR_KEY = "irma.settings.monitorName";
```

- [ ] **Step 2: Add the reader and include it in `loadSettings`**

Add this reader (e.g. after `readDockPosition`):

```ts
function readMonitorName(): string | null {
  const raw = localStorage.getItem(MONITOR_KEY);
  return raw && raw.length > 0 ? raw : null;
}
```

Replace `loadSettings` (currently lines 57-59) with:

```ts
export function loadSettings(): IrmaSettings {
  return {
    companionId: readCompanionId(),
    dockPosition: readDockPosition(),
    monitorName: readMonitorName(),
  };
}
```

- [ ] **Step 3: Add `saveCompanionPlacement`**

Add after `saveDockPosition` (which stays as-is for the settings UI):

```ts
/**
 * Persist a full placement (monitor + zone) — used by drag-drop and reset.
 * A null/empty monitorName means "primary monitor".
 */
export function saveCompanionPlacement(
  monitorName: string | null,
  dockPosition: DockPosition,
): void {
  if (monitorName && monitorName.length > 0) {
    localStorage.setItem(MONITOR_KEY, monitorName);
  } else {
    localStorage.removeItem(MONITOR_KEY);
  }
  localStorage.setItem(DOCK_KEY, dockPosition);
  void emit(CHANGE_EVENT, loadSettings());
}
```

- [ ] **Step 4: Verify types**

Run: `cd apps/desktop && npm run typecheck`
Expected: PASS (no errors). Note: `SettingsView.tsx` and `Companion.tsx` consume `loadSettings()` — adding a field is backward-compatible; they'll compile.

- [ ] **Step 5: Commit**

```bash
git add apps/desktop/src/lib/settings.ts
git commit -m "feat(companion): persist monitorName in settings"
```

---

## Task 6: Drag handlers + resume in Companion.tsx

Wire pointer-based drag on the sprite hit-target, suspend/resume the dog brain, and apply/persist the resolved drop.

**Files:**
- Modify: `apps/desktop/src/companion/Companion.tsx`

- [ ] **Step 1: Update imports**

Replace the settings import block (currently `Companion.tsx:7-13`) with:

```tsx
import {
  getCompanion,
  loadSettings,
  saveCompanionPlacement,
  subscribeSettings,
  DEFAULT_DOCK_POSITION,
  type DockPosition,
} from "../lib/settings";
```

(`saveDockPosition` is removed from this import — it's no longer used here.)

- [ ] **Step 2: Add the drag/resume refs + state**

Inside the `Companion` component, just after the existing `xRef` declaration (currently `Companion.tsx:136`), add:

```tsx
  const draggingRef = useRef<boolean>(false);
  const startXRef = useRef<number | null>(null);
  const pressRef = useRef<{
    screenX: number;
    screenY: number;
    offsetX: number;
    offsetY: number;
    moved: boolean;
  } | null>(null);
  const [placementVersion, setPlacementVersion] = useState<number>(0);
```

Add `monitorName` state next to the existing `dockPosition` state (currently `Companion.tsx:126-128`):

```tsx
  const [monitorName, setMonitorName] = useState<string | null>(
    () => loadSettings().monitorName,
  );
```

- [ ] **Step 3: Track `monitorName` in the settings subscription**

In the `subscribeSettings` effect (currently `Companion.tsx:184-190`), add the monitor setter:

```tsx
  useEffect(() => {
    const unsub = subscribeSettings((s) => {
      setCompanionId(s.companionId);
      setDockPosition(s.dockPosition);
      setMonitorName(s.monitorName);
    });
    return unsub;
  }, []);
```

- [ ] **Step 4: Replace the placement listener with a reset listener**

Replace the `companion:placement` listener effect (currently `Companion.tsx:198-212`) with:

```tsx
  // Reset placement to the primary-monitor default (tray / right-click).
  useEffect(() => {
    let cancelled = false;
    let unlisten: UnlistenFn | undefined;
    listen<void>("companion:reset-position", () => {
      if (cancelled) return;
      saveCompanionPlacement(null, DEFAULT_DOCK_POSITION);
      void invoke("position_companion").catch((e: unknown) =>
        console.error("[companion] position_companion failed", e),
      );
    })
      .then((u) => {
        if (cancelled) u();
        else unlisten = u;
      })
      .catch((e) => console.error("[companion] listen companion:reset-position failed", e));
    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, []);
```

- [ ] **Step 5: Make `moveTo` respect drag; pass `monitorName` to bounds**

In the dog-brain effect, update `moveTo` (currently `Companion.tsx:229-236`) to bail during drag:

```tsx
    const moveTo = (x: number): void => {
      if (draggingRef.current) return;
      xRef.current = x;
      const b = boundsRef.current;
      if (!b) return;
      void invoke("set_companion_pos", { x, y: b.y }).catch((e: unknown) =>
        console.error("[companion] set_companion_pos failed", e),
      );
    };
```

Update the `get_companion_bounds` call in `refreshBounds` (currently `Companion.tsx:240-242`) to pass the monitor:

```tsx
        const b = (await invoke("get_companion_bounds", {
          monitorName,
          dockPosition,
        })) as CompanionBounds;
```

- [ ] **Step 6: Honor a just-dropped start X in the bootstrap, and clear drag flag**

In the same effect, replace the bootstrap IIFE (currently `Companion.tsx:393-405`) with:

```tsx
    (async () => {
      draggingRef.current = false;
      const bounds = await refreshBounds();
      if (!bounds || cancelled) return;
      const fallbackCenter = bounds.minX + (bounds.maxX - bounds.minX) / 2;
      const startX = clamp(
        startXRef.current ?? fallbackCenter,
        bounds.minX,
        bounds.maxX,
      );
      startXRef.current = null;
      xRef.current = startX;
      moveTo(startX);
      console.info("[companion] bounds", bounds, TEST_WALK_ONLY ? "(TEST)" : "");
      if (TEST_WALK_ONLY) {
        void startWalk();
      } else {
        startCuddle();
      }
    })();
```

- [ ] **Step 7: Add the drag flag guard to bark mode and update effect deps**

In the same effect, guard `enterBarkMode` (currently `Companion.tsx:339-345`) so a drag in progress isn't interrupted:

```tsx
    const enterBarkMode = (): void => {
      if (draggingRef.current) return;
      mode = "bark";
      clearTimers();
      const facingRight = Math.random() < 0.5;
      setDog({ variant: "sit_bark", facingRight });
      console.info("[companion] enter bark mode");
    };
```

Update the effect's dependency array (currently `Companion.tsx:437` — `}, [dockPosition]);`) to:

```tsx
  }, [dockPosition, monitorName, placementVersion]);
```

- [ ] **Step 8: Add the pointer handlers + wire them onto the hit-target**

Replace the `onClick` handler (currently `Companion.tsx:443-447`) with the drag/click pointer handlers:

```tsx
  const DRAG_THRESHOLD = 4;

  const onPointerDown = (e: React.PointerEvent): void => {
    if (e.button !== 0) return; // primary button only
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    const b = boundsRef.current;
    const originX = xRef.current;
    const originY = b ? b.y : e.screenY;
    pressRef.current = {
      screenX: e.screenX,
      screenY: e.screenY,
      offsetX: originX - e.screenX,
      offsetY: originY - e.screenY,
      moved: false,
    };
  };

  const onPointerMove = (e: React.PointerEvent): void => {
    const p = pressRef.current;
    if (!p) return;
    if (!p.moved) {
      const dist = Math.hypot(e.screenX - p.screenX, e.screenY - p.screenY);
      if (dist < DRAG_THRESHOLD) return;
      p.moved = true;
      draggingRef.current = true; // suspend the dog brain's movement
    }
    void invoke("set_companion_pos", {
      x: e.screenX + p.offsetX,
      y: e.screenY + p.offsetY,
    }).catch((err: unknown) =>
      console.error("[companion] drag set_companion_pos failed", err),
    );
  };

  const onPointerUp = (e: React.PointerEvent): void => {
    const p = pressRef.current;
    pressRef.current = null;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* capture may already be released */
    }
    if (!p) return;
    if (!p.moved) {
      // A click (no meaningful movement) → toggle the main window.
      void invoke("toggle_main").catch((err: unknown) =>
        console.error("[companion] toggle_main failed:", err),
      );
      return;
    }
    // A drag → resolve the snap, apply it, persist, and resume roaming.
    void (async () => {
      try {
        const drop = (await invoke("resolve_companion_drop")) as {
          monitorName: string;
          dockPosition: DockPosition;
          x: number;
          bounds: CompanionBounds;
        };
        boundsRef.current = drop.bounds;
        startXRef.current = drop.x;
        await invoke("set_companion_pos", { x: drop.x, y: drop.bounds.y });
        draggingRef.current = false;
        saveCompanionPlacement(drop.monitorName, drop.dockPosition);
        // Force a brain re-bootstrap even if monitor/zone are unchanged.
        setPlacementVersion((v) => v + 1);
      } catch (err) {
        console.error("[companion] resolve_companion_drop failed", err);
        draggingRef.current = false;
      }
    })();
  };
```

Then update the hit-target `<div>` (currently `Companion.tsx:468-482`) to use the pointer handlers instead of `onClick`:

```tsx
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: "50%",
            cursor: "pointer",
            pointerEvents: "auto",
            touchAction: "none",
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onContextMenu={onContextMenu}
          role="button"
          aria-label="Irma companion"
        />
```

- [ ] **Step 9: Update `onContextMenu` to drop the stale argument**

Replace `onContextMenu` (currently `Companion.tsx:449-456`) with:

```tsx
  const onContextMenu = (e: React.MouseEvent): void => {
    e.preventDefault();
    void invoke("show_companion_context_menu").catch((err: unknown) =>
      console.error("[companion] show_companion_context_menu failed", err),
    );
  };
```

- [ ] **Step 10: Verify types**

Run: `cd apps/desktop && npm run typecheck`
Expected: PASS. If `clamp` is reported unused or already-in-scope, note it is defined at module scope (`Companion.tsx:106`) and reused here — no redefinition needed.

- [ ] **Step 11: Commit**

```bash
git add apps/desktop/src/companion/Companion.tsx
git commit -m "feat(companion): drag-to-place sprite with snap + resume"
```

---

## Task 7: Full build + manual verification

No frontend test runner exists; verify the integrated behavior by building and exercising the app.

**Files:** none (verification only)

- [ ] **Step 1: Type-check + production build of the frontend**

Run: `cd apps/desktop && npm run build`
Expected: `tsc --noEmit` passes and `vite build` completes with no errors.

- [ ] **Step 2: Rust build + tests**

Run: `cd apps/desktop/src-tauri && cargo test && cargo build`
Expected: `zone_tests` PASS; build succeeds.

- [ ] **Step 3: Launch the app and walk the checklist**

Run: `cd apps/desktop && npm run tauri:dev`
Then verify (from the design spec §6):
  - [ ] Click (no movement) toggles the main window.
  - [ ] Drag within the primary screen across all three zones; on release the zone + Y baseline are correct (over Dock → sits atop the Dock; sides → floor lift).
  - [ ] Drag onto a secondary screen, drop left / middle / right — middle snaps to the nearer edge; `on-dock` is never selected there.
  - [ ] After each drop she resumes roaming within the new zone only.
  - [ ] Placement (monitor + zone) survives quitting and relaunching the app.
  - [ ] "Reset Position" (tray menu and sprite right-click) returns her to left-of-dock on the primary monitor.
  - [ ] With a saved secondary monitor disconnected, relaunch falls back to the primary monitor (no crash, sane placement).
  - [ ] (Mixed-DPI only) If the live drag feels offset between a Retina and an external display, the *landing* is still correct — note it for the follow-up described in spec §4.

- [ ] **Step 4: Final commit (if any verification fixups were needed)**

```bash
git add -A
git commit -m "chore(companion): drag-to-place verification fixups"
```

(Skip if no changes were required.)

---

## Notes for the implementer

- **Coordinate spaces:** live drag uses `MouseEvent.screenX/screenY` (global CSS px) plus a fixed offset; the snap is recomputed in Rust from the real `outer_position`, so snap correctness never depends on the live-drag math. See spec §4 for the mixed-DPI fallback (switch the drag-move source to Rust `cursor_position()`), only if needed.
- **Why `placementVersion`:** dropping in the *same* monitor+zone produces no `dockPosition`/`monitorName` change, so the brain effect wouldn't re-run and roaming wouldn't resume. Bumping `placementVersion` forces a clean re-bootstrap on every drop.
- **`startXRef`:** carries the dropped landing-x into the brain bootstrap so she resumes from where you let go rather than re-centering.
- **Tauri v2 `Monitor` API used:** `name() -> Option<&String>`, `position() -> &PhysicalPosition<i32>`, `size() -> &PhysicalSize<u32>`, `scale_factor() -> f64`, plus `WebviewWindow::{outer_position, outer_size, available_monitors, primary_monitor}`.
