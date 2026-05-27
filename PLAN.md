# PLAN.md — Irma Phase 1–3 build

Authoritative engineering plan. CLAUDE.md and docs/ARCHITECTURE.md are the spec; this file is the *how*. Phase 4 work (RAG, Gemini, real sprite engine, MCP) is explicitly out of scope here.

## Repo layout (end of Phase 3)

```
irma/
├── .gitignore
├── CLAUDE.md
├── PLAN.md
├── docs/
│   ├── ARCHITECTURE.md
│   └── KICKOFF_PROMPT.md
├── apps/desktop/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── index.html                       # main window entry
│   ├── companion.html                   # companion window entry
│   ├── src/
│   │   ├── main.tsx                     # dashboard root mount
│   │   ├── companion.tsx                # companion sprite root mount
│   │   ├── styles.css                   # Tailwind v4 entry (@import "tailwindcss")
│   │   ├── lib/
│   │   │   ├── api.ts                   # typed fetch client (StandupBrief, /refresh)
│   │   │   ├── sse.ts                   # EventSource wrapper, typed AgentState stream
│   │   │   └── types.ts                 # TS mirror of Pydantic Signal / StandupBrief / AgentState
│   │   ├── companion/
│   │   │   ├── Companion.tsx            # window root; SSE subscribe; click → toggle_main
│   │   │   ├── Sprite.tsx               # manifest-driven CSS-sprite/placeholder renderer
│   │   │   └── useSpriteAnimation.ts    # rAF tick → frame index from manifest.fps
│   │   └── main/
│   │       ├── App.tsx                  # dashboard chrome (drag region, close→hide)
│   │       ├── StandupView.tsx          # renders StandupBrief sections
│   │       ├── components/
│   │       │   ├── BriefHeader.tsx
│   │       │   ├── BlockerList.tsx
│   │       │   ├── ConflictList.tsx
│   │       │   ├── ScheduleList.tsx
│   │       │   └── Narrative.tsx
│   │       └── mockBrief.ts             # Phase 1 fixture; dev-fallback once /standup is live
│   ├── public/sprites/manifest.json     # exact ARCHITECTURE §3 contract
│   └── src-tauri/
│       ├── Cargo.toml
│       ├── tauri.conf.json              # v2 schema; two windows, tray, frontend dist
│       ├── build.rs
│       ├── icons/                       # default Tauri icons (placeholder set)
│       └── src/
│           ├── main.rs                  # thin entry → irma_lib::run()
│           ├── lib.rs                   # builder: windows, tray, activation policy, commands
│           ├── windows.rs               # position_companion + toggle_main + monitor listener
│           └── tray.rs                  # tray menu + click handlers
└── services/api/
    ├── pyproject.toml                   # uv-managed; ruff + mypy strict config
    ├── uv.lock
    ├── .env.example
    ├── .python-version                  # 3.12
    ├── README.md
    ├── irma_api/
    │   ├── __init__.py
    │   ├── main.py                      # `python -m irma_api` → uvicorn
    │   ├── app.py                       # FastAPI factory; lifespan wires scheduler + state bus
    │   ├── config.py                    # pydantic-settings Settings
    │   ├── logging.py                   # structlog config
    │   ├── models/
    │   │   ├── __init__.py
    │   │   ├── signal.py                # Signal, ScheduleItem
    │   │   └── brief.py                 # StandupBrief
    │   ├── agents/
    │   │   ├── __init__.py
    │   │   ├── base.py                  # Observer Protocol
    │   │   ├── time_agent.py            # aiogoogle GCal
    │   │   ├── codebase_agent.py        # asyncio git subprocess
    │   │   └── lead_agent.py            # Claude synthesis → StandupBrief
    │   ├── store/
    │   │   ├── __init__.py
    │   │   ├── sqlite.py                # aiosqlite DAOs
    │   │   └── migrations.py            # idempotent schema bootstrap
    │   ├── routers/
    │   │   ├── __init__.py
    │   │   ├── signals.py               # GET /signals, POST /refresh
    │   │   ├── standup.py               # GET /standup
    │   │   └── state.py                 # GET /state, GET /stream (SSE)
    │   └── runtime/
    │       ├── __init__.py
    │       ├── state.py                 # AgentState enum + asyncio broadcaster
    │       └── scheduler.py             # APScheduler AsyncIOScheduler wrapper
    └── tests/
        ├── conftest.py
        ├── test_signal_schema.py
        ├── test_codebase_agent.py       # seeds a tmp git repo, asserts signal shape
        ├── test_state_bus.py            # fan-out + drop-oldest backpressure
        └── test_brief_parse.py          # defensive JSON parse (fenced/raw/retry)
```

## Phase 1 — Companion + UI shell (`apps/desktop`)

### Init commands (non-interactive)
```bash
cd apps
npm create tauri-app@latest desktop -- \
    --template react-ts \
    --manager npm \
    --identifier com.amit.irma \
    --yes
cd desktop
npm install -D tailwindcss@^4 @tailwindcss/vite
npm install @tauri-apps/api@^2
npm install -D @tauri-apps/cli@^2
```
After scaffold, overwrite/extend the files below.

### Per-file responsibility
- `package.json` — pins React 18, Vite 5, Tauri 2, Tailwind 4. Scripts: `dev`, `build`, `tauri dev`, `tauri build`.
- `vite.config.ts` — `@tailwindcss/vite`, two-entry `rollupOptions.input` (`index.html`, `companion.html`), `server.strictPort: true`, port `1420`, `clearScreen: false`.
- `index.html` / `companion.html` — minimal shells importing `src/main.tsx` / `src/companion.tsx`.
- `src/styles.css` — `@import "tailwindcss";` + `@theme` tokens for Irma palette (charcoal `#10131a`, indigo `#7c83ff`, amber `#ffb86b`, violet `#b386ff`, teal `#5bd1c1`).
- `src/lib/types.ts` — TS mirror of `Signal`, `StandupBrief`, `ScheduleItem`, `AgentState`. Front-end SoT.
- `src/lib/api.ts` — `fetchStandup()`, `forceRefresh()` over `VITE_IRMA_API` (default `http://127.0.0.1:8765`).
- `src/lib/sse.ts` — typed `subscribeAgentState(onState)` over `EventSource`, auto-reconnect, cleanup handle.
- `src/companion/Sprite.tsx` — fetches `/sprites/manifest.json`; renders a 96×96 sprite. If `manifest.image` resolves, renders a `<div>` with `background-image` + `background-position` per frame index. Otherwise renders a CSS-painted placeholder avatar whose color + animation map to `AgentState` (idle indigo pulse, observing teal scan, thinking violet shimmer, alert amber blink). Tick rate driven by `manifest.states[state].fps`.
- `src/companion/useSpriteAnimation.ts` — `useEffect` rAF loop returning `{ frameIndex }` derived from `(performance.now() * fps / 1000) % frames.length`.
- `src/companion/Companion.tsx` — root for companion window. Phase 1: local `useState<AgentState>('idle')`. Phase 3: `subscribeAgentState`. Click → `invoke('toggle_main')`. Body is zero-margin; root spans `w-screen h-screen`.
- `src/main/App.tsx` — dashboard root. Custom drag region via `data-tauri-drag-region` on the title strip. Close button → `getCurrentWindow().hide()`. Loads `mockBrief` in Phase 1; Phase 3 swaps to `fetchStandup()` + SSE-triggered re-fetch.
- `src/main/StandupView.tsx` + `components/*` — render every `StandupBrief` field with Tailwind utility classes. No UI library.
- `src/main/mockBrief.ts` — realistic fixture using §10 epics so the dashboard is alive in Phase 1.
- `public/sprites/manifest.json` — exact JSON from ARCHITECTURE §3.

### Rust (src-tauri)
- `Cargo.toml` — `tauri = { version = "2", features = ["tray-icon"] }`, `tauri-plugin-tray`, `serde`, `serde_json`, `tokio = { features = ["macros","rt-multi-thread"] }`.
- `tauri.conf.json` — v2 schema. `productName: "Irma"`, identifier `com.amit.irma`. `app.windows`:
  - `companion`: `decorations:false, transparent:true, alwaysOnTop:true, skipTaskbar:true, focus:false, shadow:false, resizable:false, width:96, height:96, url:"companion.html", visible:true`.
  - `main`: `decorations:false, transparent:false, visible:false, width:960, height:640, url:"index.html"`.
  - `frontendDist: "../dist"`, `devUrl: "http://localhost:1420"`.
- `src/main.rs` — calls `irma_lib::run()`.
- `src/lib.rs` — builds the app, registers `position_companion` + `toggle_main`, in `setup` applies `ActivationPolicy::Accessory` (macOS), installs the tray, positions the companion, and hooks `WindowEvent::CloseRequested` on `main` to `prevent_close` + `hide`.
- `src/windows.rs` — `position_companion` implements ARCHITECTURE §1 math; `IRMA_DOCK_CLEARANCE` env override (default 80.0). `toggle_main` toggles visibility + focus. A monitor change listener re-runs positioning.
- `src/tray.rs` — `TrayIconBuilder` with menu "Toggle Irma" / "Settings" / "Quit"; left-click tray = toggle_main.

## Phase 2 — Observer backend (`services/api`)

### Init commands
```bash
mkdir -p services/api && cd services/api
uv init --package --name irma-api --python 3.12
uv add fastapi "uvicorn[standard]" pydantic pydantic-settings aiosqlite sqlmodel \
       aiogoogle tenacity apscheduler anthropic structlog httpx
uv add --dev ruff mypy pytest pytest-asyncio pytest-httpx types-requests
```

### Per-file responsibility
- `pyproject.toml` — `[project]` deps as above. `[tool.ruff]` line-length 100, target `py312`, lint `E,F,I,UP,B,SIM,ASYNC,RUF`. `[tool.mypy]` `strict = true`, `plugins = ["pydantic.mypy"]`. `[tool.pytest.ini_options]` `asyncio_mode = "auto"`.
- `.env.example` — exactly ARCHITECTURE §6 keys, plus `IRMA_API_HOST=127.0.0.1`, `IRMA_API_PORT=8765`.
- `irma_api/config.py` — `Settings(BaseSettings)`. SecretStr for API keys / OAuth. `irma_repos: list[Path]` via comma-split `field_validator`. `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`. Cached `get_settings()`.
- `irma_api/logging.py` — `structlog` JSON in non-TTY, key=value in TTY.
- `irma_api/models/signal.py` — `Signal`, `ScheduleItem` (ARCHITECTURE §5). `Signal.hash_key()` → sha256 over canonicalized fields, for cache-invalidation.
- `irma_api/models/brief.py` — `StandupBrief` (ARCHITECTURE §4).
- `irma_api/store/sqlite.py` — async connection. Tables: `signals(id pk, source, kind, title, detail, ts, meta_json, hash_key UNIQUE, collected_at)`; `briefs(id pk, signal_set_hash UNIQUE, payload_json, generated_at)`. DAOs: `upsert_signals`, `latest_signals`, `get_cached_brief`, `cache_brief`.
- `irma_api/store/migrations.py` — `async def ensure_schema(conn)` called from lifespan.
- `irma_api/agents/base.py` — `class Observer(Protocol): name: str; async def collect(self) -> list[Signal]: ...`.
- `irma_api/agents/time_agent.py` — aiogoogle GCal; `events.list(calendarId="primary", timeMin=now, timeMax=now+7d, singleEvents=True, orderBy="startTime", maxResults=50)`. 429 → exponential backoff via `tenacity.AsyncRetrying`. Missing/invalid creds → return `[]` and set `self.unlinked=True` (runtime layer surfaces an alert notice).
- `irma_api/agents/codebase_agent.py` — for each repo path: validate `.git/` exists, else log warn + skip. Spawns `git -C <repo> log --since='3 days ago' --no-merges --date=iso-strict --pretty=format:'%H%x1f%an%x1f%aI%x1f%s%x1f%b%x1e' --numstat` via `asyncio.create_subprocess_exec`. Parses `\x1e` records / `\x1f` fields + numstat trailers. Emits per-commit signals + one `kind="velocity_summary"` per repo.
- `irma_api/runtime/state.py` — `AgentState(StrEnum)`. `StateBus` with bounded per-subscriber `asyncio.Queue(maxsize=16)`, `subscribe()` context manager, `publish()` fans out with `put_nowait` (drop-oldest on `QueueFull`).
- `irma_api/runtime/scheduler.py` — `Scheduler` wraps `AsyncIOScheduler` with `IntervalTrigger(minutes=settings.irma_refresh_minutes)`. Job calls the same `refresh()` coroutine the router uses.
- `irma_api/routers/signals.py` — `GET /api/v1/signals`, `POST /api/v1/refresh`. The shared `refresh()` coroutine drives bus transitions; Phase 2 path = `observing → idle`.
- `irma_api/routers/standup.py` — Phase 2 stub returning 503 "not implemented".
- `irma_api/routers/state.py` — Phase 2 stub for `/state`; SSE arrives in Phase 3.
- `irma_api/app.py` — `create_app()` factory. Lifespan opens the SQLite connection (on `app.state.db`), runs migrations, instantiates observers + state bus + scheduler, then starts scheduler. CORS allows `http://localhost:1420`, `tauri://localhost`, `https://tauri.localhost`. Mounts routers at `/api/v1`.
- `irma_api/main.py` — `uvicorn.run("irma_api.app:create_app", factory=True, host=..., port=..., log_config=None)`.

## Phase 3 — Lead synthesis + reactive sprite

### Per-file responsibility (new / extended)
- `irma_api/agents/lead_agent.py` — `LeadAgent(settings, client: anthropic.AsyncAnthropic)`:
  - `_system_prompt()` establishes the Irma persona (PMO chief-of-staff, terse, anticipatory, conflict-aware). Output is ONLY a JSON object matching `StandupBrief` — no prose, no fences.
  - `_user_content(signals)` groups by source, summarizes commit bodies (≤200 chars), caps event descriptions, attaches an inferred `epic` tag per signal (heuristic regex over title/detail/repo → "Zero-Shot Video World Model" / "MIT DL & Bar-Ilan M.Sc" / null) so cross-epic conflicts are easy for Claude to surface.
  - `synthesize(signals)` — hash signal set, hit cache if present; otherwise `client.messages.create(model=settings.anthropic_model, max_tokens=1500, system=..., messages=[...])`, `_parse_brief()` strips fences and slices `{...}`, validates via Pydantic. On failure, one retry asks Claude to "Reply with ONLY the JSON object". Second failure → `BriefSynthesisError`. Result is cached.
- `irma_api/routers/standup.py` — `GET /api/v1/standup` reads latest signals, runs `lead_agent.synthesize()`, transitions bus `thinking` → `alert` (if blockers/conflicts) or `idle`, returns brief. `503 Retry-After: 5` on cold start.
- `irma_api/routers/state.py` — `GET /api/v1/state` (current state); `GET /api/v1/stream` (`text/event-stream` SSE). Subscribes to `StateBus`, emits an initial snapshot, fans out `event: state\ndata: <enum>\n\n`, sends a 15s keep-alive comment, cancels cleanly on disconnect.
- `irma_api/runtime/state.py` — adds `current()` accessor so new SSE subscribers get the live snapshot before deltas.
- `irma_api/routers/signals.py` — `refresh()` now drives the full cycle `observing → thinking → idle/alert`, calls `lead_agent.synthesize()` to prime cache.
- Desktop wiring:
  - `src/companion/Companion.tsx` — replaces local `useState` with `subscribeAgentState(setState)`.
  - `src/main/App.tsx` — uses `fetchStandup()`. Re-fetches on SSE transitions to `idle` / `alert`. `mockBrief.ts` becomes a `VITE_USE_MOCK=1` fallback only.
- Tests:
  - `tests/test_codebase_agent.py` — seeds a tmp git repo, asserts commit + velocity signal shape.
  - `tests/test_state_bus.py` — multi-subscriber fan-out + drop-oldest under backpressure.
  - `tests/test_brief_parse.py` — fenced JSON, dirty JSON, malformed text; one retry path; `BriefSynthesisError` after two failures. Mocks `AsyncAnthropic`.

## Key technical decisions
- **Two HTML entries, one Vite dev server.** Each Tauri window points at its own URL — no runtime window-router.
- **Sprite placeholder honors manifest contract.** Swapping in `irma_sheet.png` is config-only.
- **`AgentState` is a `StrEnum`** so SSE wire format = the enum value verbatim.
- **Bus backpressure = drop-oldest.** Late UI cues are worse than dropping intermediate transitions.
- **Defensive Claude parse.** Strip → slice → Pydantic → one retry. No `response_format`; the JSON contract lives in the system prompt.
- **Cache key = sorted-signal hash.** Same inputs → same brief. `/refresh` upserts new signals → new hash → resynth.
- **`uv` over Poetry.** Faster, single-tool, native pyproject.
- **No MCP for calendar (spec §7).** REST + aiogoogle. MCP is a Phase 4 inversion.

## Verification

End of **Step 0**:
```bash
cd /Users/amit/Documents/Code/Irma
git log --oneline
test -f PLAN.md && test -f docs/ARCHITECTURE.md && test -f docs/KICKOFF_PROMPT.md && echo OK
```
**STOP for user confirmation before Phase 1.**

End of **Phase 1**:
```bash
cd apps/desktop
npm install
npm run tauri dev
# Expect: sprite anchored bottom-left, no Dock tile, tray icon present, click → main toggles, close main → hides.
IRMA_DOCK_CLEARANCE=120 npm run tauri dev   # sprite shifts up
```

End of **Phase 2**:
```bash
cd services/api
uv sync
uv run ruff check .
uv run mypy --strict irma_api
uv run pytest
uv run python -m irma_api &
curl -s -XPOST localhost:8765/api/v1/refresh
curl -s localhost:8765/api/v1/signals | jq '.[0:3]'
```

End of **Phase 3**:
```bash
cd services/api
uv run python -m irma_api &
curl -s -XPOST localhost:8765/api/v1/refresh
curl -s localhost:8765/api/v1/standup | jq
curl -Ns localhost:8765/api/v1/stream &
curl -s -XPOST localhost:8765/api/v1/refresh   # observe state transitions

cd ../../apps/desktop && npm run tauri dev
# Expect: sprite flips to 'alert' on a cross-epic conflict;
# dashboard renders the live brief with Zero-Shot Video World Model vs MIT DL conflict.
```

Strict gates for Phase 2 & 3 commits: `ruff check .` clean, `mypy --strict irma_api` clean, `pytest` green.
