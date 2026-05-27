# Irma

*A local-first desktop AI chief-of-staff — a small dog who lives beside your Dock.*

Irma is a passive intelligence layer. She observes read-only data streams — your Google Calendar and local git repos — synthesizes them into a daily standup brief, and surfaces blockers and cross-epic conflicts in her own voice. She's embodied as a small dog character that sits next to the macOS Dock; clicking her opens the dashboard. Her sprite reacts in real time to what her backend agents are doing (`idle / observing / thinking / alert`).

She runs entirely on your machine. Synthesis can be powered by Claude (Anthropic) or by a local model via Ollama — toggle with one env var.

## What you see

- **Companion** — a borderless, transparent, always-on-top window anchored bottom-left of your work area. Just the sprite. macOS runs the app under `ActivationPolicy::Accessory`, so there's no Dock tile of its own; the dog *is* the presence. A menu-bar tray icon handles quit/settings.
- **Dashboard** — opens on click. Renders Irma's standup brief: velocity narrative, blockers, conflicts, the next 7 days of salient events, her recommended next move, and a small chat panel for asking her things directly.

## Quick start

You need two processes: the FastAPI backend, and the Tauri desktop app.

### 1. Backend

```bash
cd services/api
uv sync
cp .env.example .env          # fill the backend you want (see below)
uv run irma-api               # serves http://127.0.0.1:8765
```

Minimum config in `.env`:

| Backend | Required |
|---|---|
| **Claude** | `IRMA_LLM_BACKEND=anthropic`, `ANTHROPIC_API_KEY=…` |
| **Local Ollama** | `IRMA_LLM_BACKEND=ollama`, `OLLAMA_MODEL=qwen2.5:7b` (and `ollama serve` running) |

Google Calendar + git repos are optional — Irma boots in degraded mode without them and the chat panel still works.

### 2. Desktop app

```bash
cd apps/desktop
npm install
npm run tauri dev
```

The sprite anchors itself beside the Dock; click to open the dashboard.

## Project layout

```
irma/
├── apps/desktop/           # Tauri v2 (Rust) + React + Vite + Tailwind
│   ├── src/                # companion window + dashboard
│   ├── src-tauri/          # windows, tray, accessory policy, positioning
│   └── public/sprites/     # sprite sheet + manifest
├── services/api/           # FastAPI (Python 3.12+, fully async)
│   └── src/irma_api/
│       ├── agents/         # observers (TimeAgent, CodebaseAgent), LeadAgent, LLM clients
│       ├── routers/        # /signals, /standup, /state + /stream (SSE), /chat
│       ├── runtime/        # AgentState bus, APScheduler wrapper
│       └── store/          # aiosqlite + cached briefs
├── docs/
│   ├── ARCHITECTURE.md     # design rationale + contracts
│   ├── BACKEND.md          # walk through services/api code
│   ├── DESKTOP.md          # walk through apps/desktop code
│   └── LLM.md              # pluggable Anthropic ↔ Ollama backend
├── CLAUDE.md               # authoritative product spec
└── PLAN.md                 # phase-by-phase engineering plan
```

## Status

- **Phase 1** ✓ Companion + dashboard shell, accessory policy, tray, bottom-left positioning, placeholder sprite.
- **Phase 2** ✓ Async observer backend, `Signal` schema, `TimeAgent` (GCal), `CodebaseAgent` (git), SQLite store.
- **Phase 3** ✓ `LeadAgent` synthesis, `StandupBrief`, `AgentState` SSE stream, reactive sprite.
- **Phase 3.5** ✓ Pluggable LLM backend (Anthropic ↔ Ollama); chat endpoint and dashboard chat panel.
- **Phase 4** Deferred: ChromaDB RAG, additional observers, real sprite-sheet animation engine.

## Tech stack

| Layer | Choice |
|---|---|
| Desktop shell | Tauri v2 (Rust), two windows + tray, accessory activation policy |
| Frontend | React 18 + Vite + TypeScript + Tailwind v4 |
| Backend | FastAPI (Python 3.12+), fully async |
| Synthesis LLM | Claude (`anthropic` SDK) or local Ollama, hot-swappable |
| Calendar | Google Calendar REST via `aiogoogle` + OAuth2 |
| Storage | SQLite via `aiosqlite` |
| Scheduling | APScheduler `AsyncIOScheduler` |
| Config | `pydantic-settings`, `.env` |

## Further reading

- `docs/ARCHITECTURE.md` — design decisions, window model, agent pipeline, prompt contract, schemas
- `docs/BACKEND.md` — how the FastAPI service is wired, module by module
- `docs/DESKTOP.md` — how the Tauri + React app is wired, module by module
- `docs/LLM.md` — the pluggable LLM backend; adding a new provider
- `CLAUDE.md` — the canonical product spec (Claude Code reads this on every turn)
