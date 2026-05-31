# Companion drag-to-place — design

> Replace the right-click/tray placement menu with direct drag-and-drop of the
> sprite. The user grabs Irma, drags her anywhere (including across monitors),
> and on release she snaps into one of the existing zones.

## 1. Goal

Today the companion's placement (`left-of-dock` / `on-dock` / `right-of-dock`)
is chosen from a context menu and is locked to the primary monitor. Replace
that with **drag-to-place**:

- Grab the sprite and drag it freely in X **and** Y, across all monitors.
- On release, she **snaps to a zone** and reverts Y to that zone's baseline.
- She then **roams within that zone** (existing strip-roam behavior).
- Placement persists across launches.
- The 3-way placement menu is replaced by a single **"Reset Position"** item.

## 2. Behavior model (the contract)

### Zones are unchanged
The three zones remain exactly as the code computes them today:
`left-of-dock`, `on-dock` ("on top of" the Dock), `right-of-dock`. Drag merely
*selects* a zone by drop position instead of a menu choosing it.

### During drag
- The window follows the cursor freely in X and Y. The window is repositioned
  to keep a fixed offset under the cursor, so the cursor stays over the sprite's
  hit-target and pointer events keep firing (window-chases-cursor).
- The autonomous "dog brain" (walk loop, cuddle/sit/lay timers, bark mode) is
  **suspended** for the duration of the drag.

### On release — snap rules
Resolved entirely in Rust from the window's actual position (not from trusted JS
coordinates), so the landing is always geometrically correct:

1. **Monitor:** the monitor whose bounds contain the window center becomes her
   new home monitor (she can now live on a secondary screen; today she's locked
   to primary). Fallback: primary monitor.
2. **Zone:**
   - **Primary (Dock) monitor** — three zones, by window-center X relative to the
     Dock footprint (same math as today's strips):
     - left of `dock_left` → `left-of-dock`
     - right of `dock_right` → `right-of-dock`
     - between them → `on-dock`
   - **Secondary monitor (no Dock)** — only two zones, split at monitor center:
     - center X < monitor center → `left-of-dock`
     - center X > monitor center → `right-of-dock`
     - exact tie → random pick (left/right)
     - `on-dock` is **never** selected on a secondary monitor.
3. **Y baseline** reverts automatically per zone (already implemented in
   `compute_bounds`): `on-dock` → full `dock_clearance` (sits atop the Dock);
   `left`/`right` → `BESIDE_DOCK_LIFT` (floor lift).
4. **Landing X:** her dropped X, clamped into the resolved zone's `[min_x, max_x]`
   strip — she lands where you let go (within the zone) and roams from there.

### Roaming
After snap she resumes the existing left↔right strip-roam, but bounded to the
resolved zone on the resolved monitor:
- **Primary:** `left-of-dock` / `on-dock` / `right-of-dock` strips, as today.
- **Secondary:** left half `[monitor_left, center]` or right half
  `[center, monitor_right]` (less the sprite width). No `on-dock` half.

### Click vs drag
- A primary-button press that moves **< 4px** before release is a **click** →
  `toggle_main` (unchanged behavior).
- Past the 4px threshold it becomes a **drag**; the click is suppressed.
- Right-click (`contextmenu`) still opens the menu (now "Reset Position").
  Non-primary buttons never start a drag.

## 3. Architecture & components

### 3.1 `src-tauri/src/windows.rs`

**`compute_bounds` — add monitor selection + secondary-screen halves.**
- Refactor the current `compute_bounds(window, dock_position)` so the monitor is
  a parameter rather than always `target_monitor` (primary):
  - `fn compute_bounds_for(window, monitor: &Monitor, dock_position: &str) -> CompanionBounds`
  - Keep the existing Dock-footprint strip math for the **primary** monitor.
  - When `monitor` is **not** the primary, branch to center-split halves:
    - `left-of-dock` → `[monitor_left, center]`
    - `right-of-dock` → `[center, monitor_right]`
    - `on-dock` should not occur on secondary; if it does, fall back to nearest
      half (defensive).
  - Y/clearance logic is unchanged (`on-dock` → `dock_clearance`, else
    `BESIDE_DOCK_LIFT`).
- Add `fn monitor_by_name(window, name: &str) -> Option<Monitor>` and a resolver
  that picks: saved monitor by name → primary → cursor.

**`get_companion_bounds` — accept the saved monitor.**
```rust
#[tauri::command]
pub fn get_companion_bounds(
    window: WebviewWindow,
    monitor_name: Option<String>,   // NEW — None = primary
    dock_position: String,
) -> Result<CompanionBounds, String>
```
Resolve the monitor (by name, else primary), then `compute_bounds_for`.

**`resolve_companion_drop` — NEW command, the snap brain.**
```rust
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ResolvedDrop {
    pub monitor_name: String,
    pub dock_position: String,   // resolved zone
    pub x: f64,                  // landing X, clamped into the zone strip
    pub bounds: CompanionBounds,
}

#[tauri::command]
pub fn resolve_companion_drop(window: WebviewWindow) -> Result<ResolvedDrop, String>
```
Implementation:
1. Read `window.outer_position()` + `window.outer_size()` (physical); compute the
   window center in physical global coords.
2. Find the monitor containing that center (iterate `available_monitors()`;
   fallback primary). Capture its `name()` (fallback to a synthetic id if `None`).
3. Compare against `primary_monitor()` to decide primary vs secondary.
4. Compute the zone per §2 snap rules (Dock footprint via existing `dock_width()`
   on primary; center-split + random tie-break on secondary).
   - Random tie-break: a tiny PRNG seeded from the low bits of the window
     position (no `rand` dep needed) — exact center is a measure-zero case.
5. `compute_bounds_for(window, &monitor, &zone)`, then
   `x = clamp(window_center_x - sprite_w/2, bounds.min_x, bounds.max_x)`.
6. Return `ResolvedDrop`.

**`set_companion_pos` — reused for live drag.** It already sets an arbitrary
`(x, y)` via `set_position(LogicalPosition)`, so the drag-move path reuses it (Y
is free during drag). No separate drag-move command.

**`place_companion` / reset.** `position_companion` already re-anchors to
`left-of-dock` on primary — reuse it for "Reset Position".

### 3.2 `src/lib/settings.ts`

- Extend `IrmaSettings` with `monitorName: string | null` (key
  `irma.settings.monitorName`; `null` = primary).
- `loadSettings()` returns `{ companionId, dockPosition, monitorName }`.
- New `saveCompanionPlacement(monitorName: string | null, dockPosition: DockPosition)`
  — writes both keys and emits `irma:settings-changed`.
- Keep `saveDockPosition` only if still used; otherwise fold into the above.
- Migration: a missing `monitorName` reads as `null` (primary) — no breakage.

### 3.3 `src/companion/Companion.tsx`

**State:** add `monitorName` alongside `dockPosition`; the dog-brain effect keys
on `[dockPosition, monitorName]` so a drop (which updates both via the
settings broadcast) tears down and re-runs the brain → fresh bootstrap → resumes
roaming at the new bounds.

**`refreshBounds`** passes `{ monitorName, dockPosition }` to `get_companion_bounds`.

**Drag handlers** on the hit-target div (component scope, using refs):
- `draggingRef` (suspends the brain) and `pressRef` (start screen coords + window
  offset + moved flag).
- `onPointerDown` (button 0 only): `setPointerCapture`, record `e.screenX/Y` and
  the window origin offset (`origin - screen`); not yet a drag.
- `onPointerMove`: once moved > 4px, set `draggingRef = true` (brain loops bail);
  compute `newOrigin = (screenX + offsetX, screenY + offsetY)` and
  `invoke("set_companion_pos", { x, y })`.
- `onPointerUp` / `onPointerCancel`: `releasePointerCapture`.
  - Not dragged → `invoke("toggle_main")` (replaces the old `onClick`).
  - Dragged → `invoke("resolve_companion_drop")` → set final position via
    `set_companion_pos(x, bounds.y)`, then
    `saveCompanionPlacement(monitorName, dockPosition)`. The settings broadcast
    updates state → brain re-runs and resumes roaming. Reset `draggingRef`.
- The brain's movement paths (`moveTo`, `step`, `enterBarkMode`) early-return
  while `draggingRef.current` is true.

**Reset listener:** replace the `companion:placement` listener with
`companion:reset-position` → `saveCompanionPlacement(null, DEFAULT_DOCK_POSITION)`
then `invoke("position_companion")`.

**`onContextMenu`:** still calls `show_companion_context_menu` (now arg-less).

### 3.4 `src-tauri/src/tray.rs` + `src/lib.rs`

- `build_tray_menu` and `show_companion_menu`: replace the three
  `CheckMenuItem`s with a single `MenuItem` id `reset_position` → "Reset Position".
- `show_companion_context_menu(app)` drops the `dock_position` param.
- Menu-event handlers in **both** `tray.rs` (builder `on_menu_event`) and
  `lib.rs` (`app.on_menu_event` in setup): replace the three
  `companion_*_of_dock` arms with `"reset_position" => emit("companion:reset-position")`.
- Register `resolve_companion_drop` in the `invoke_handler!` list; update
  `get_companion_bounds`'s new signature (Tauri picks up the extra arg).

## 4. Coordinate handling (the one fiddly part)

- **Live drag** uses `MouseEvent.screenX/screenY` (global CSS px) + a fixed
  offset to the window origin, passed to `set_companion_pos` as logical coords.
  On macOS the global points space is scale-consistent across displays, so this
  is accurate on a single-DPI setup and close on mixed-DPI.
- **The snap result does not depend on this.** `resolve_companion_drop` reads the
  window's real `outer_position` in Rust and recomputes everything, so even if the
  live drag drifts under mixed scale factors, the final landing is correct.
- **Verify on the real multi-monitor setup** (Retina + external): if the live
  drag feels offset under mixed DPI, switch the drag-move source from `screenX/Y`
  to Rust `window.cursor_position()` (physical) converted per the monitor under
  the cursor. Snap correctness is unaffected either way.

## 5. Out of scope

- No new sprite art or animation states (drag uses existing frames; the dog
  simply holds its current variant while being moved).
- No change to the FastAPI backend, SSE, or brief logic.
- Dock-on-secondary-display configs (rare) are treated as "secondary = no Dock";
  primary monitor is always the Dock screen.

## 6. Manual test checklist

- [ ] Click (no movement) still toggles the main window.
- [ ] Drag within the primary screen across all three zones; verify zone + Y
      baseline on release (over Dock → sits atop Dock; sides → floor lift).
- [ ] Drag onto a secondary screen, drop left / middle / right — middle snaps to
      nearest edge; `on-dock` never selected there.
- [ ] After each drop she resumes roaming within the new zone only.
- [ ] Placement (monitor + zone) survives an app restart.
- [ ] "Reset Position" (tray + sprite right-click) returns her to left-of-dock on
      primary.
- [ ] Disconnect the saved secondary monitor, relaunch → falls back to primary.
