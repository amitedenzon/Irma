# KICKOFF_PROMPT.md — Irma

> Verbatim brief used to bootstrap the Irma build. CLAUDE.md and ARCHITECTURE.md remain authoritative; this captures the staffing contract and phase ordering.

**Role:** Act as a Staff-level engineer pairing with an AI Researcher / Backend Engineer. Skip tutorials, junior commentary, and basic explanations. Ship production-grade, strictly-typed, async code. No placeholder bodies (`# implement here`) — implement fully or scope explicitly to deferred Phase 4.

**Read first:** `CLAUDE.md` and `docs/ARCHITECTURE.md`. They are the authoritative spec for **Irma**, a local desktop AI PMO assistant embodied as a character beside the macOS Dock. Honor every constraint there (window model, accessory policy, `Signal`/`StandupBrief` schemas, AgentState→sprite contract, REST-not-MCP calendar, async + `ruff`/`mypy --strict`, secrets via env).

**Before writing code:** produce `PLAN.md` — the full directory tree and a per-file responsibility list for Phases 1–3 — and stop for my confirmation.

**Then build, phase by phase (commit at each phase boundary):**

**Phase 1 — Companion + UI shell (`apps/desktop`)**
- Give exact **non-interactive** init commands (`npm create tauri-app@latest irma -- --template react-ts --manager npm --yes`, etc.), pinned to **Tauri v2**.
- Provide the precise `tauri.conf.json` v2 config and Rust (`src-tauri`) for: two windows (`companion`, `main`); `companion` borderless/transparent/always-on-top/skip-taskbar/non-focusable, sized to sprite bbox; `main` frameless, hidden on launch; `ActivationPolicy::Accessory`; a tray icon (Toggle Irma / Settings / Quit); a `position_companion` command (bottom-left, beside Dock, `IRMA_DOCK_CLEARANCE` tunable); click-sprite → toggle `main`.
- React/Tailwind: a `companion` sprite component that reads `public/sprites/manifest.json` and animates per AgentState (CSS placeholder avatar honoring the manifest contract — no art yet); a `main` "Standup Brief" dashboard shell rendering `StandupBrief` (mock data until Phase 3).

**Phase 2 — Observer backend (`services/api`)**
- Async FastAPI with modular routers, `pydantic-settings` config, committed `.env.example`.
- `Signal` schema; `Observer` protocol; `TimeAgent` (Google Calendar REST via `aiogoogle`, OAuth2, next 7 days, 429 backoff, graceful no-token degrade); `CodebaseAgent` (`asyncio.create_subprocess_exec` git log, last 3 days, per-commit + velocity_summary signals, missing-repo tolerance); `SignalStore` on `aiosqlite`.
- Endpoints `GET /api/v1/signals`, `POST /api/v1/refresh`.

**Phase 3 — Lead PMO synthesis + reactive sprite**
- `LeadAgent`: build the Irma-persona system prompt, call Claude via the async `anthropic` Messages API (`ANTHROPIC_MODEL` from env), return a validated `StandupBrief` (defensive JSON parse, one retry). Cache on signal-hash; `/refresh` busts it.
- `GET /api/v1/standup` wired end-to-end. `AgentState` bus + `GET /api/v1/stream` (SSE); transitions per ARCHITECTURE §3. APScheduler periodic re-observation. Wire the desktop companion to the SSE stream so the sprite flips to `alert` on blockers/conflicts, and the dashboard renders the live brief.
- Use the §10 test-data epics (Zero-Shot Video World Model; MIT DL / Bar-Ilan M.Sc) to demonstrate a real cross-epic conflict in the brief.

**Do NOT build Phase 4** (ChromaDB RAG, Gemini, real sprite engine, MCP tools) — leave the documented seams only.

**Output:** complete files with their paths as headers; strict type hints; `asyncio` for all I/O; runnable `ruff`/`mypy --strict`-clean code. End each phase with the exact commands to run it (backend + desktop) and verify.
