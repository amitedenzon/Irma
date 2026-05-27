# `apps/desktop/` — Irma's Tauri + React app

Two windows + a tray:

- `companion` — borderless, transparent, always-on-top sprite anchored beside the macOS Dock
- `main` — the dashboard (standup brief + chat with Irma)

For a code walk (Rust commands, React entries, sprite manifest, dashboard composition), see [`../../docs/DESKTOP.md`](../../docs/DESKTOP.md).

For the deep design rationale (window model, positioning math, sprite state machine), see [`../../docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).

## Dev

```bash
npm install
npm run tauri dev               # launches both windows
VITE_USE_MOCK=1 npm run dev     # browser-only, no backend, uses mockBrief
```

The backend must be running for live data — see [`../../services/api/README.md`](../../services/api/README.md).
