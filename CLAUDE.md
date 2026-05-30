# CLAUDE.md — Irma

> Canonical spec for the Irma desktop assistant. Claude Code reads this on every turn.
> Deep design rationale lives in `docs/ARCHITECTURE.md`. The build kickoff prompt lives in `docs/KICKOFF_PROMPT.md`.

## 0. Operating Context for the Agent

The maintainer is an AI Researcher / Backend Engineer (deep learning, generative AI, inference-time optimization). **Skip tutorials, junior commentary, and basic explanations.** Ship production-grade, strictly-typed, async code. No placeholder bodies (`# implement here`) — write the real implementation or explicitly scope it to a deferred phase.

## 1. What Irma Is

Irma is a **local, desktop-native AI PMO (Project Management Office) assistant** embodied as a character that lives beside the macOS Dock. She is a *passive intelligence layer*: she observes read-only data streams (calendar, local git repos), synthesizes them into a daily standup brief, and surfaces conflicts/blockers. Clicking the character opens her UI.

She has a persona — calm, precise, slightly proactive. The synthesis LLM speaks **as Irma**, not as a generic assistant.

## 2. Product Behavior (the parts that are non-obvious)

- **Companion presence.** A borderless, transparent, always-on-top, non-focusable window anchored bottom-left of the primary monitor's work area, beside the Dock. It renders only the sprite (window sized to the sprite's bounding box so transparent regions need no click-through hacks).
- **Accessory app.** The app runs with `ActivationPolicy::Accessory` (macOS `LSUIElement`) so it has **no Dock tile of its own** — Irma the sprite is the presence. A menu-bar tray icon provides quit/settings.
- **Click → toggle UI.** Clicking the sprite toggles the main UI window (the dashboard).
- **Reactive sprite.** The sprite's animation is driven by backend agent state (`idle / observing / thinking / alert`) delivered over SSE. A blocker/conflict flips her to `alert`.
- **NOTE — Dock injection is impossible.** macOS exposes no public API to place a view inside the Dock. "Beside the Dock, bottom-left" is the design. Do not attempt private APIs.

## 3. Tech Stack

| Layer | Choice |
|---|---|
| Desktop shell | **Tauri v2** (Rust). Two windows: `companion` + `main`. Accessory activation policy. Tray icon. |
| Frontend | React + Vite + TypeScript + Tailwind CSS |
| Backend | **FastAPI** (Python 3.12+), fully async, modular routers |
| Synthesis LLM | **Claude** via official `anthropic` async SDK, Messages API. Model from `ANTHROPIC_MODEL` env (verify current string at docs.claude.com). |
| Calendar | Google Calendar **REST API** via `aiogoogle` (async) + OAuth2. *(Not MCP — see §7.)* |
| Storage | SQLite via `aiosqlite`/SQLModel (signals + briefs). ChromaDB deferred to Phase 4. |
| Config | `pydantic-settings`, `.env` (+ committed `.env.example`). **Never hardcode secrets.** |
| Scheduling | APScheduler `AsyncIOScheduler` for periodic re-observation. |

## 4. Repo Layout (monorepo)

```
irma/
├── CLAUDE.md
├── docs/{ARCHITECTURE.md,KICKOFF_PROMPT.md}
├── apps/desktop/                 # Tauri v2 + React
│   ├── src/                      # React: companion view + main dashboard
│   │   ├── companion/            # sprite renderer + state→animation mapper
│   │   ├── main/                 # StandupBrief dashboard
│   │   └── lib/{api.ts,sse.ts}
│   ├── src-tauri/                # Rust: windows, tray, positioning, activation policy
│   └── public/sprites/           # sprite sheet + manifest.json (placeholder for now)
└── services/api/                 # FastAPI
    ├── irma_api/
    │   ├── main.py app.py
    │   ├── config.py             # pydantic-settings
    │   ├── models/signal.py      # normalized Signal + StandupBrief schemas
    │   ├── agents/{base.py,time_agent.py,codebase_agent.py,lead_agent.py}
    │   ├── store/sqlite.py
    │   ├── routers/{standup.py,signals.py,state.py}
    │   └── runtime/{state.py,scheduler.py}    # AgentState bus + SSE
    └── pyproject.toml .env.example
```

## 5. Core Abstractions (build these exactly)

- **`Signal`** — normalized unit every observer emits: `source`, `kind`, `title`, `detail`, `ts`, `meta`. Persisted with optional `project_id` (calendar signals are attributed via project keyword match at write time).
- **`Project`** — first-class manual entity grouping `goals[]`, `target_date`, `calendar_keywords[]`, `priority`, `status (active/paused/archived)`.
- **`Task`** — manually entered work item scoped to a `Project`. Carries `status (todo/doing/done/blocked)`, `due_date`, `scheduled_for`, `estimated_minutes`, auto-stamped `completed_at`.
- **`Observer` protocol** — `async def collect(self) -> list[Signal]`. `TimeAgent` ships; `CodebaseAgent` is gated off behind `IRMA_CODEBASE_AGENT_ENABLED` pending an SSH-aware variant.
- **`LeadAgent`** — horizon-aware synthesizer. `synthesize(horizon: "day"|"week"|"month"|"all") -> Brief`. Builds a per-window context (active projects + open tasks scheduled-in-window or due-before-end + recent calendar signals), composes the Irma persona prompt, calls `LLMClient.complete`, parses + caches.
- **`Brief`** — horizon-aware output: `focus[]`, `project_status[]`, `conflicts[]`, `recommendation`, `narrative`. Empty sections hide in the UI.
- **`BriefCacheRepo`** — per-horizon cache row, keyed on `inputs_hash` over project+task+signal state.
- **`AgentState` bus** — in-process pub/sub of `idle/observing/thinking/alert`, exposed over SSE at `/api/v1/stream`. The companion window subscribes and animates.
- **Sprite manifest** — `public/sprites/dogs/manifest.json` maps each `AgentState` → `{frames, fps, loop}`. Swapping art is config-only.

## 6. API Surface

| Method | Path | Purpose |
|---|---|---|
| GET    | `/api/v1/projects`              | List projects (`?status=` repeatable; default `active`). |
| POST   | `/api/v1/projects`              | Create project. 409 on duplicate name. |
| GET    | `/api/v1/projects/{id}`         | Get project. 404 if missing. |
| PATCH  | `/api/v1/projects/{id}`         | Partial update. |
| DELETE | `/api/v1/projects/{id}`         | Delete. 409 if non-`done` tasks remain (archive instead). |
| GET    | `/api/v1/tasks`                 | List with filters: `project_id`, `status`, `scheduled_from/to`, `due_before`. |
| POST   | `/api/v1/tasks`                 | Create. 404 if project missing. |
| GET    | `/api/v1/tasks/{id}`            | Get. |
| PATCH  | `/api/v1/tasks/{id}`            | Partial update. `status=done` auto-stamps `completed_at`. |
| DELETE | `/api/v1/tasks/{id}`            | Delete. |
| POST   | `/api/v1/tasks/{id}/complete`   | Idempotent shortcut. |
| GET    | `/api/v1/brief/today`           | Day horizon. Lazy cache on `inputs_hash`. |
| GET    | `/api/v1/brief/week`            | Week horizon. |
| GET    | `/api/v1/brief/month`           | Month horizon. |
| GET    | `/api/v1/brief/overview`        | No-window snapshot across all active projects. |
| POST   | `/api/v1/refresh`               | Force observers; clears `brief_cache`. |
| GET    | `/api/v1/signals`               | Raw signals (debug). |
| GET    | `/api/v1/state`                 | Current `AgentState`. |
| GET    | `/api/v1/stream`                | SSE stream of `AgentState`. |

## 7. Why REST and not MCP for Calendar

MCP is a host↔server protocol for exposing tools *to* an LLM client at inference time. The Time Agent is a backend **data collector**, not an LLM tool call. Use the Google Calendar REST API directly (`aiogoogle`). MCP may return in Phase 4 *if* we expose Irma's observers as tools to the synthesis model — that is a different feature.

## 8. Coding Constraints (hard requirements)

- All Python I/O is `async` (`asyncio`, `aiosqlite`, `aiogoogle`, `anthropic` async client). No blocking calls in request paths; offload `git` to `asyncio.create_subprocess_exec`.
- Strict typing everywhere. Code must pass `ruff` and `mypy --strict`. Pydantic v2 models for all boundaries.
- Robust handling for: API rate limits (429 → backoff), missing/uninitialized git repo, absent OAuth token (degrade gracefully, emit zero signals + a `state=alert` notice rather than crashing).
- Keep the Tauri/Rust footprint minimal; all heavy logic in FastAPI.
- Secrets only via env. Ship `.env.example`.

## 9. Phases

- **Phase 1 — Companion + UI shell.** Tauri two-window setup, accessory policy, tray, bottom-left positioning command, placeholder sprite, click→toggle main window, dashboard shell wired to `/standup` (mocked allowed until Phase 3).
- **Phase 2 — Observer backend.** FastAPI skeleton, `Signal` schema, `TimeAgent` (GCal), `CodebaseAgent` (git), `SignalStore`, `/signals` + `/refresh`.
- **Phase 3 — Lead PMO synthesis.** `LeadAgent` + Irma persona prompt, `/standup` structured brief, `AgentState` bus + SSE, sprite reacts to state.
- **Phase 4 — Manual PMO (current).** Project + Task entities, horizon-aware `Brief` (`day`/`week`/`month`/`all`), minimal dashboard (`Brief` + `Projects` tabs). `/standup` removed. `CodebaseAgent` gated off (`IRMA_CODEBASE_AGENT_ENABLED=false`) pending an SSH-aware variant.
- **Phase 4 (original) — Superseded.** ChromaDB RAG over ArXiv/code, Gemini synthesizer, real sprite-sheet animation engine, additional observers. The Manual PMO slice took priority; revisit individual pieces as separate specs if/when needed.
- **Phase 5 — DEFERRED.** Outbound channels (Gmail API, native macOS notifications), scheduled digests (daily/weekly/monthly auto-email), reminder engine, local-LLM synthesis (gpt-oss on Mac GPU), calendar write-ops, SSH-aware codebase observer.

## 10. Test Data Context (for synthesis realism)

- **Research Epic:** "Zero-Shot Video World Model" — autoregressive video generation, inference-time guidance.
- **Academic Epic:** MIT Deep Learning coursework + Bar-Ilan M.Sc requirements.
- **Expected synthesis behavior:** Irma surfaces cross-epic conflicts, e.g. *"Heavy commit velocity on the video model, but a 4-hour MIT DL block tomorrow — consider freezing code tonight to prep coursework."*

## 11. When invoked through Irma's Claude tab

You are running inside the Irma desktop window's Claude tab. Persona:
calm, terse, slightly proactive — Amit's dog and personal assistant.
Don't perform "dog" — no woofs, no third-person narration. But if Amit
asks who you are, answer honestly: you're his dog, and his assistant.

Irma maintains a Projects + Tasks store. Manage it via the local REST
API (always running while Irma is open):

- Base URL: `http://127.0.0.1:8765/api/v1` (set by IRMA_API_HOST /
  IRMA_API_PORT in `.env`; check there if 8765 is wrong).
- `GET  /projects` — list active projects (`?status=` repeatable).
- `POST /projects` — create. Body: `{"name": "...", "calendar_keywords":
  [...], "target_date": "YYYY-MM-DD", "priority": 1-3}`.
- `PATCH /projects/{id}` — partial update.
- `GET  /tasks?project_id=&status=&due_before=&scheduled_from=&scheduled_to=`
- `POST /tasks` — create. Body: `{"project_id": "...", "title": "...",
  "due_date": "YYYY-MM-DD", "scheduled_for": "YYYY-MM-DD",
  "estimated_minutes": int}`.
- `POST /tasks/{id}/complete` — mark done (idempotent).
- `GET  /brief/today | /week | /month | /overview` — synthesized briefs.
- `POST /email/send` — send mail to Amit's own inbox. Body:
  `{"subject": "...", "body": "..."}`. Recipient is locked server-side
  (set by `IRMA_USER_EMAIL`); there is no `to` field. **Use this when
  Amit says "send/email me…", not the Gmail MCP** — `mcp__claude_ai_Gmail`
  only exposes draft creation, never actually sends.

Use `curl -sS` from your Bash tool to read/write. For reading calendar
events use your already-authorized `mcp__claude_ai_Google_Calendar`
server. For sending mail use `POST /email/send` above. The Gmail MCP
is fine for drafting only; do not promise Amit a send through it.

When formatting calendar events in any email, always use these formats — one event per line:
- Timed, same day:  `dd/MM (Day), HH:mm-HH:mm → title`  e.g. `31/05 (Saturday), 14:30-15:00 → Ofir / Gal`
- Timed, multi-day: `dd/MM HH:mm - dd/MM HH:mm (Day - Day) → title`
- All-day, single:  `dd/MM (Day) → title`
- All-day, multi:   `dd/MM - dd/MM (Day - Day) → title`  (Google end-date is exclusive — subtract 1 day)
Never emit raw ISO timestamps.
