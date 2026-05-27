# ARCHITECTURE.md — Nofari

Design rationale and contracts. `CLAUDE.md` is the authoritative summary; this expands the non-trivial parts.

## 1. Desktop Window Model (Tauri v2)

Two windows + a tray:

### `companion`
- `decorations: false`, `transparent: true`, `alwaysOnTop: true`, `skipTaskbar: true`, `focus: false`, `shadow: false`, `resizable: false`.
- Sized to the sprite bounding box (e.g. 96×96 logical). Because the window equals the sprite, transparent click-through is unnecessary — the whole window *is* the clickable sprite.
- Positioned by a Rust command at startup and on monitor/resize changes.
- A single `onClick` (Tauri event) toggles `main`.

### `main`
- `decorations: false` (custom drag region in React), `transparent: false`, hidden on launch (`visible: false`).
- Toggled show/hide on companion click. On close, hide rather than destroy.

### Activation policy & tray
- `app.set_activation_policy(ActivationPolicy::Accessory)` on macOS → no Dock tile, no app-switcher entry. Nofari's only visible presence is the sprite + a menu-bar tray icon (Settings, Toggle Nofari, Quit).

### Positioning math (Rust command `position_companion`)
```
let mon = window.current_monitor()?.unwrap();
let scale = mon.scale_factor();
let area = mon.size().to_logical::<f64>(scale);     // work area
let pos  = mon.position().to_logical::<f64>(scale);
let margin_x = 12.0;
let dock_clearance = 80.0;                            // approx; configurable
let x = pos.x + margin_x;                             // LEFT edge, beside dock
let y = pos.y + area.height - SPRITE_H - dock_clearance;
window.set_position(LogicalPosition::new(x, y))?;
```
Dock height isn't exposed by a public API; `dock_clearance` is a tunable in settings. "Beside the Dock, bottom-left" is the achievable target (see CLAUDE.md §2 caveat).

## 2. Agent Pipeline

```
                ┌─────────────┐
   GCal  ──────▶│  TimeAgent  │──┐
                └─────────────┘  │   list[Signal]   ┌────────────┐   StandupBrief   ┌─────────┐
                                 ├─────────────────▶│ LeadAgent  │─────────────────▶│  /standup│
   git   ──────▶┌─────────────┐  │   (normalized)   │ (Claude)   │                   └─────────┘
                │CodebaseAgent│──┘                  └────────────┘
                └─────────────┘                            │ emits AgentState transitions
                                                           ▼
                                                  AgentState bus ── SSE ──▶ companion sprite
```

All observers implement:
```python
class Observer(Protocol):
    name: str
    async def collect(self) -> list[Signal]: ...
```

### TimeAgent
- `aiogoogle` async client, OAuth2 (offline refresh token in `.env`/token store).
- Pulls `events.list` for `[now, now+7d]`, `singleEvents=True`, ordered by start.
- Maps each event → `Signal(source="calendar", kind="event", title=summary, detail=description, ts=start, meta={end, attendees, location})`.
- 429 → exponential backoff (`tenacity`). Missing token → return `[]`, push `alert` with a "calendar not linked" notice.

### CodebaseAgent
- Repo paths from config (list). For each: `asyncio.create_subprocess_exec("git","-C",path,"log","--since=3 days ago","--pretty=...","--numstat")`.
- Parse into per-commit `Signal(source="codebase", kind="commit", title=subject, detail=body, ts=author_date, meta={hash, files_changed, insertions, deletions, repo})`.
- Also emit one `kind="velocity_summary"` Signal per repo (commit count, net churn).
- Non-repo path / git missing → skip path, log, continue.

### LeadAgent (synthesis)
- Input: `list[Signal]`. Builds a compact, structured prompt (see §4). Calls Claude (async, streaming optional). Returns `StandupBrief`.
- **Caching:** hash the sorted signal set; if unchanged since last brief, return cached brief (avoids paying for identical synthesis). `/refresh` busts it.

## 3. AgentState Bus & Sprite State Machine

`AgentState ∈ {idle, observing, thinking, alert}`. In-process `asyncio`-based pub/sub (an `asyncio.Queue` per SSE subscriber, fanned out from a single broadcaster). Transitions:

```
idle ──refresh/scheduler──▶ observing ──collect done──▶ thinking ──synth done──▶ idle
  ▲                                                                                │
  └──────────────────────── (no blockers) ◀──────────────────────────────────────┘
thinking ── brief.blockers or brief.conflicts non-empty ──▶ alert ──user opens UI──▶ idle
```

### Sprite manifest (`public/sprites/manifest.json`)
```json
{
  "image": "nofari_sheet.png",
  "frameWidth": 96, "frameHeight": 96,
  "states": {
    "idle":      { "frames": [0,1,2,1], "fps": 4,  "loop": true },
    "observing": { "frames": [3,4,5],   "fps": 8,  "loop": true },
    "thinking":  { "frames": [6,7],     "fps": 6,  "loop": true },
    "alert":     { "frames": [8,9,8,9], "fps": 10, "loop": true }
  }
}
```
The companion renderer is a small `<canvas>`/CSS-sprite component that subscribes to SSE and plays the clip for the current state. **Until a real sheet exists**, ship a placeholder: a CSS-styled circular avatar that changes color/animation per state and reads the same manifest contract — so dropping in `nofari_sheet.png` later is config-only.

## 4. Synthesis Prompt Contract

System prompt establishes the **Nofari persona** (PMO chief of staff: terse, anticipatory, conflict-aware) and demands JSON-only output matching `StandupBrief`. User content is the serialized signals grouped by source with explicit epic tagging. Request structured output; parse defensively (strip fences, validate with Pydantic, one retry on parse failure). Keep token use lean — summarize commit bodies, cap event descriptions.

```python
class StandupBrief(BaseModel):
    generated_at: datetime
    velocity: str                     # 1-2 sentences on momentum
    blockers: list[str]
    conflicts: list[str]              # cross-epic / schedule clashes
    schedule: list[ScheduleItem]      # next ~7d salient items
    recommendation: str               # the single highest-leverage action
    narrative: str                    # Nofari's voice, <= 4 sentences
```

## 5. Data Schemas (single source of truth)

```python
class Signal(BaseModel):
    source: Literal["calendar", "codebase"]
    kind: str
    title: str
    detail: str = ""
    ts: datetime
    meta: dict[str, Any] = {}

class ScheduleItem(BaseModel):
    ts: datetime
    title: str
    epic: str | None = None
```

## 6. Config (`.env.example`)
```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6        # verify latest at docs.claude.com
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_OAUTH_REFRESH_TOKEN=
NOFARI_REPOS=/abs/path/repo1,/abs/path/repo2
NOFARI_REFRESH_MINUTES=30
NOFARI_DOCK_CLEARANCE=80
NOFARI_DB_PATH=./nofari.db
```

## 7. Phase 4 (deferred — design notes only)
- **RAG:** ChromaDB collections for ArXiv PDFs + code; a `KnowledgeAgent` that retrieves context for the brief.
- **Gemini synthesizer:** swap/ensemble at the `LeadAgent` boundary (it already isolates the LLM call).
- **Sprite engine:** real sheet, easing between states, idle micro-animations, drag-to-reposition persisted to settings.
- **MCP:** optionally expose observers as MCP tools to the synthesis model.
