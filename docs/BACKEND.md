# BACKEND.md — `services/api/`

How the FastAPI service is wired. Read top-to-bottom; every section maps to one or two files.

The deep design rationale lives in `ARCHITECTURE.md`. This doc is the **code walk** — what each module does, how they fit, where to look when something breaks.

## App lifecycle — `irma_api/app.py`

`create_app()` is a FastAPI factory consumed by `uvicorn.run(..., factory=True)`. The `lifespan` async-context-manager owns every long-lived resource so they share the request handlers' event loop:

1. **Settings** (`get_settings()` — cached singleton, see config below).
2. **SignalStore** — opens the SQLite connection, runs idempotent migrations.
3. **StateBus** — in-process pub/sub for `AgentState` transitions.
4. **Observers** — `[TimeAgent(settings), CodebaseAgent(settings.irma_repos)]`. Plug-compatible via the `Observer` protocol.
5. **LLM client** — built by `build_llm_client(settings)` based on `IRMA_LLM_BACKEND`. Returns `None` if the chosen backend is unconfigured (e.g. Anthropic selected but no API key); the app boots in degraded mode rather than crashing. See `docs/LLM.md`.
6. **LeadAgent** — built only if an LLM client exists. Imported lazily (`importlib.import_module`) so a Phase 2-only deploy without the synthesis module still boots.
7. **Scheduler** — `APScheduler.AsyncIOScheduler` ticking every `IRMA_REFRESH_MINUTES` to call the same `refresh()` coroutine `/api/v1/refresh` does.

Shutdown closes the Ollama httpx client (if used) and the SQLite connection. CORS allows `localhost:1420`, `tauri://localhost`, `https://tauri.localhost` so the desktop app can talk over either dev or packaged origin.

`app.state` carries everything routers need: `settings`, `store`, `bus`, `observers`, `llm`, `lead_agent`, `scheduler`. Routers read from `request.app.state.*`.

## Config — `irma_api/config.py`

Strict `pydantic-settings` model. Loads `process env > .env`. Secrets wrapped in `SecretStr` so they never leak via `repr()`. Notable fields:

- `irma_llm_backend: Literal["anthropic", "ollama"]` — drives `build_llm_client`.
- `anthropic_api_key`, `anthropic_model` — used when backend is `anthropic`.
- `ollama_base_url`, `ollama_model` — used when backend is `ollama`. Defaults: `http://127.0.0.1:11434`, `qwen2.5:7b`.
- `irma_repos: list[Path]` — accepts comma-separated paths from `.env` via a `field_validator`.
- `irma_refresh_minutes` — scheduler cadence.
- `irma_db_path` — relative paths resolve from `services/api/` cwd.

`get_settings()` is `lru_cache`d so the same `Settings` instance is reused across the process.

## Data models — `irma_api/models/`

Single source of truth for every wire boundary; the frontend `src/lib/types.ts` is a hand-mirror.

- `signal.py` — `Signal { source, kind, title, detail, ts, meta }`. `source: Literal["calendar","codebase"]`. `Signal.hash_key()` produces a stable sha256 over canonicalized fields for store dedup + cache invalidation. `ScheduleItem` lives here too.
- `brief.py` — `StandupBrief { generated_at, velocity, blockers, conflicts, schedule, recommendation, narrative }`. `has_attention_signal` property is true iff `blockers` or `conflicts` is non-empty — used to flip the sprite to `alert`.

## Observers — `irma_api/agents/`

All observers implement:

```python
class Observer(Protocol):
    name: str
    async def collect(self) -> list[Signal]: ...
```

defined in `agents/base.py`. The same module declares `LeadAgentProtocol` so Phase 2 code can refer to the Phase 3 surface without importing it.

### `TimeAgent` (`agents/time_agent.py`)
- `aiogoogle` async client; OAuth2 refresh token from env.
- Pulls `events.list(calendarId="primary", timeMin=now, timeMax=now+7d, singleEvents=True, orderBy="startTime", maxResults=50)`.
- Each event → `Signal(source="calendar", kind="event", ...)`.
- 429 → exponential backoff via `tenacity.AsyncRetrying`. Missing/invalid creds → returns `[]` and sets a flag the runtime can lift into a "calendar not linked" alert.

### `CodebaseAgent` (`agents/codebase_agent.py`)
- For each path in `IRMA_REPOS`, validates `.git/` exists (else skip + warn).
- Spawns `git -C <repo> log --since='3 days ago' --no-merges --date=iso-strict --pretty=… --numstat` via `asyncio.create_subprocess_exec` (no blocking).
- Parses `\x1e`-separated records / `\x1f` fields + numstat trailers.
- Emits per-commit `Signal(kind="commit")` plus one `kind="velocity_summary"` per repo (count + net churn).

### `LeadAgent` (`agents/lead_agent.py`)
- Takes an `LLMClient` (not the Anthropic SDK directly — see `docs/LLM.md`), a `SignalStore`, and `Settings`.
- `synthesize(signals)`:
  1. Hash the signal set (`compute_signal_set_hash`). If cached brief exists, return it.
  2. Build user content: signals grouped by source, each tagged with an inferred `epic` (regex over title/detail/repo → `"Zero-Shot Video World Model"` / `"MIT DL & Bar-Ilan M.Sc"` / `null`). Commit bodies summarized to ≤200 chars.
  3. Call `llm.complete(system=_SYSTEM_PROMPT, messages=…, max_tokens=1500)`.
  4. `_parse_brief()` strips Markdown fences, slices the first `{…}` window, validates with Pydantic.
  5. On parse failure: append the bad assistant reply + a "reply with ONLY the JSON object" follow-up, call once more. Second failure → `BriefSynthesisError`.
  6. Cache the brief by signal-set hash.
- System prompt establishes Irma's persona — calm, terse, slightly proactive PMO chief of staff, and (per `docs/LLM.md`) a small dog. JSON-only output discipline lives in the prompt, not in `response_format`.

## LLM clients — `irma_api/agents/llm.py`

The provider-agnostic abstraction. Full walkthrough in `docs/LLM.md`. In short:

```python
class LLMClient(Protocol):
    backend: str
    model: str
    async def complete(self, *, system: str, messages: list[ChatTurn], max_tokens: int = 1500) -> str: ...
```

Two adapters: `AnthropicLLM` (wraps `AsyncAnthropic`) and `OllamaLLM` (long-lived `httpx.AsyncClient` against `/api/chat`, generous read timeout for cold local models). Factory: `build_llm_client(settings) -> LLMClient | None`.

## Routers — `irma_api/routers/`

All mounted under `/api/v1`.

| File | Endpoints | Purpose |
|---|---|---|
| `signals.py` | `GET /signals`, `POST /refresh` | Inspect raw collected signals; force re-observation (drives the full `observing → thinking → idle/alert` cycle and primes the brief cache). |
| `standup.py` | `GET /standup` | Returns the cached/fresh `StandupBrief`. 503s if `LeadAgent` isn't configured or no signals have been collected yet. |
| `state.py` | `GET /state`, `GET /stream` | Current `AgentState`; SSE stream of transitions. SSE emits an initial snapshot, then each `event: state\ndata: <enum>\n\n`, with a 15s keep-alive comment. |
| `chat.py` | `POST /chat` | Free-form chat with Irma's persona. Body: `{messages: [{role, content}]}`. Returns `{reply, backend, model}`. Publishes `thinking → idle/alert` on the bus so the sprite reacts. |

The shared `run_refresh()` coroutine in `routers/signals.py` is what both `POST /refresh` and the scheduler call — single code path for collection + caching.

## Runtime — `irma_api/runtime/`

### `state.py` — the bus
- `AgentState(StrEnum) = {idle, observing, thinking, alert}`. `StrEnum` → SSE wire value = the enum string verbatim.
- `StateBus` is an `asyncio` broadcaster. Each subscriber gets a bounded `asyncio.Queue(maxsize=16)`. `publish()` fans out via `put_nowait`; on `QueueFull` it drops the **oldest** queued state — late UI cues are worse than dropping intermediate transitions.
- `subscribe()` is an async context manager. `current()` lets new subscribers get the live snapshot before deltas.

### `scheduler.py`
Tiny wrapper around `AsyncIOScheduler` with an `IntervalTrigger(minutes=settings.irma_refresh_minutes)`. Lifespan owns start + shutdown.

## Storage — `irma_api/store/`

- `sqlite.py` — async DAOs over `aiosqlite`. Two tables:
  - `signals(id, source, kind, title, detail, ts, meta_json, hash_key UNIQUE, collected_at)` — `hash_key` enforces idempotent upsert from observers.
  - `briefs(id, signal_set_hash UNIQUE, payload_json, generated_at)` — `LeadAgent` cache. Same inputs → same brief; `/refresh` upserts new signals → new hash → resynth.
- `migrations.py` — `ensure_schema(conn)` called once from lifespan. Idempotent.
- `compute_signal_set_hash(signals)` — canonicalizes + hashes the input set for the brief cache key.

## Logging — `irma_api/logging.py`

`structlog`, JSON in non-TTY, key=value in TTY. All log lines are structured (`event="app.ready", llm_backend="ollama", …`) so grepping logs in dev and shipping them to a structured store in prod use the same data.

## Entry points

- `irma_api/main.py` — `uvicorn.run("irma_api.app:create_app", factory=True, host=settings.irma_api_host, port=settings.irma_api_port, log_config=None)`.
- `irma_api/__main__.py` — calls `main()`. Lets you do `python -m irma_api`.
- `pyproject.toml` `[project.scripts]` exposes `irma-api = "irma_api:main"`, so `uv run irma-api` is the canonical boot command.

## Strict gates

Every PR must pass:

```bash
uv run ruff check .
uv run mypy --strict src/irma_api
uv run pytest
```

`pyproject.toml` enforces `ruff` (E, F, I, UP, B, SIM, ASYNC, RUF) and `mypy --strict`. `asyncio_mode = "auto"` for tests.
