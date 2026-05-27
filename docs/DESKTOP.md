# DESKTOP.md — `apps/desktop/`

How the Tauri + React app is wired. This is the **code walk**; the design rationale (window model, positioning math, sprite manifest contract) lives in `ARCHITECTURE.md`.

## Two windows, one Vite dev server

The app runs **two** windows from the same Vite dev server. No runtime router — each Tauri window points at its own HTML entry.

| Window | HTML | TS entry | Purpose |
|---|---|---|---|
| `companion` | `companion.html` | `src/companion.tsx` | The sprite beside the Dock |
| `main` | `index.html` | `src/main.tsx` | The dashboard |

`vite.config.ts` exposes both as `rollupOptions.input`. `tauri.conf.json` declares both under `app.windows` and points them at `companion.html` / `index.html` via `devUrl`/`frontendDist`.

## Rust side — `src-tauri/src/`

Minimal Rust footprint; everything heavy lives in Python.

### `lib.rs`
- Builds the Tauri app, registers `invoke_handler!` for the four custom commands: `position_companion`, `toggle_main`, `get_companion_bounds`, `set_companion_pos`.
- In `setup`: applies `ActivationPolicy::Accessory` on macOS (**no Dock tile, no app-switcher entry** — the dog *is* the presence), then `windows::wire_windows(app)` and `tray::init(app.handle())`.

### `windows.rs`
- `position_companion` — runs the math in `ARCHITECTURE §1`: pulls the current monitor's logical work area, places the sprite at `(monitor.x + 12, monitor.y + area.height − sprite_h − dock_clearance)`. `IRMA_DOCK_CLEARANCE` env var overrides the default 80 px.
- `toggle_main` — show + focus, or hide. On `WindowEvent::CloseRequested` for `main`, `prevent_close` + hide rather than destroy.
- `get_companion_bounds` / `set_companion_pos` — used when the sprite resizes its window to match its bounding box.
- A monitor change listener re-runs positioning when displays change.

### `tray.rs`
- `TrayIconBuilder` with menu items "Toggle Irma" / "Settings" / "Quit". Left-click on the tray invokes `toggle_main`.

### `main.rs`
Thin entry — calls `irma_lib::run()`.

## Frontend — `src/`

### Entry points
- `companion.tsx` → mounts `<Companion />` into `#root` in `companion.html`. Body has zero margin; root spans `w-screen h-screen`.
- `main.tsx` → mounts `<App />` into `#root` in `index.html`.
- `styles.css` → `@import "tailwindcss";` plus `@theme` tokens for the Irma palette (`irma-bg`, `irma-surface`, `irma-text`, `irma-mute`, `irma-border`, `irma-indigo`, `irma-amber`, `irma-violet`, `irma-teal`). Use these tokens — they're the project's design language; don't reach for raw hex.

### Shared lib — `src/lib/`

| File | What it does |
|---|---|
| `types.ts` | TS mirror of the Pydantic models (`Signal`, `StandupBrief`, `ScheduleItem`, `AgentState`, `SpriteManifest`, `ChatMessage`, `ChatResponse`). The single source of truth on the frontend. Keep it in sync by hand when backend models change. |
| `api.ts` | Typed fetch client. `fetchStandup()`, `fetchSignals()`, `forceRefresh()`, `sendChat(messages)`. Base URL from `VITE_IRMA_API` (default `http://127.0.0.1:8765`). |
| `sse.ts` | `subscribeAgentState(onState)` over `EventSource`. Auto-reconnects (the browser handles it); errors are swallowed so the console isn't noisy when the backend is offline. |

### Companion — `src/companion/`

- `Companion.tsx` — root for the companion window. Subscribes to the `AgentState` SSE stream, renders `<Sprite state={…} />`. Click → `invoke('toggle_main')`.
- `Sprite.tsx` — manifest-driven sprite renderer. Reads `/sprites/dogs/manifest.json`. If `manifest.image` resolves, renders a `<div>` with `background-image` + `background-position` per frame index. Otherwise falls back to a CSS-painted placeholder avatar whose color + animation map to `AgentState` (idle indigo pulse, observing teal scan, thinking violet shimmer, alert amber blink). **The placeholder honors the same manifest contract as the real sheet** — dropping in a finished sprite sheet is config-only, no code changes.
- `useSpriteAnimation.ts` — tiny `useEffect` rAF loop returning `{ frameIndex }` derived from `(performance.now() * fps / 1000) % frames.length`. Driven by `manifest.states[state].fps`.

### Dashboard — `src/main/`

- `App.tsx` — dashboard chrome. Custom drag region via `data-tauri-drag-region` on the title strip. Close button routes through `invoke('toggle_main')` so the companion's `main:visibility` listener fires (it needs that to exit bark mode). On mount it `fetchStandup()` and subscribes to SSE; re-fetches on transitions into `idle` or `alert` (i.e. when the backend has just settled with a fresh brief). `VITE_USE_MOCK=1` swaps in `mockBrief` for design work without the backend.
- `StandupView.tsx` — composes the brief sections: `BriefHeader`, `Narrative`, side-by-side `BlockerList` + `ConflictList`, `ScheduleList`, then a `NextMove` callout.
- `components/` — one file per dashboard section (`BriefHeader`, `Narrative`, `BlockerList`, `ConflictList`, `ScheduleList`). All hand-rolled Tailwind, no UI library.
- `components/ChatPanel.tsx` — free-form chat with Irma. Local message history, `Enter` to send (`Shift+Enter` for newline), busy indicator, error surface, backend/model footer. Calls `sendChat(messages)`. Rendered below the standup view in `App.tsx` and remains usable even when no brief is loaded yet (so you can test the LLM backend before observing anything).
- `mockBrief.ts` — Phase 1 fixture; remains as a `VITE_USE_MOCK=1` dev fallback.

## Sprite assets — `public/sprites/dogs/`

Sprite sheet PNG frames (`Dogs-Remastered-*.png`) and a `manifest.json` mapping each `AgentState` to `{ frames, fps, loop }`. The manifest contract is in `ARCHITECTURE §3`.

## Build & dev

```bash
npm install
npm run dev              # Vite alone (browser only — no Tauri windows)
npm run tauri dev        # Tauri shell with both windows
npm run tauri build      # production build
```

`VITE_IRMA_API` overrides the backend URL. `VITE_USE_MOCK=1` swaps the dashboard to `mockBrief.ts` so you can iterate on UI without the backend running.

## Style conventions

- Use Tailwind utilities; rely on the `irma-*` design tokens defined in `styles.css`.
- No CSS-in-JS, no styled-components, no component library — keep the surface area honest.
- Each section component owns its own border / surface / spacing; the dashboard composes them with `space-y-6`.
