# Daily Email Brief — Design

> Status: approved (brainstorming). Next: implementation plan.
> Date: 2026-05-30

## Problem

Today the brief is an in-app **Brief** tab (`BriefView` + `LeadAgent.synthesize("day")`),
and a separate **Refresh** icon button re-runs observers. The maintainer wants the
brief to come to their **inbox** instead:

1. Remove the in-app Brief tab.
2. Every morning at **08:00 Asia/Jerusalem**, auto-send a daily brief by email.
3. The brief shows **progress vs. the day before** (per-project task movement).
4. The brief surfaces **deadlines / special calendar events in the next 3 days**.
5. Replace the Refresh icon button with a **Brief** button that re-sends today's
   brief to the inbox on demand.

## Decisions (locked during brainstorming)

| Question | Decision |
|---|---|
| In-app Brief tab | **Email-only.** Remove the tab; brief lives in email (8am auto + on-demand button). |
| Progress richness | **Per-project delta** — snapshot per-project open/done counts each send; report day-over-day change. |
| Missed 8am (app asleep/closed) | **Strict 8am only.** Fires only if the process is running at 8am. No startup catch-up. The Brief button is the manual fallback. |
| 3-day lookahead sources | **Tasks + calendar.** Task `due_date`/`scheduled_for` ∪ Google Calendar events in `[today, today+3]`. |

## Existing infrastructure this builds on

- `tools/resend.py::ResendSendTool` — recipient-locked (`IRMA_USER_EMAIL`) plain-text
  sender via Resend REST. Already proven by `scripts/email_today_calendar.py`.
- `tools/calendar.py::ReadCalendarTool` — async Google Calendar reader, degrades
  gracefully when OAuth is absent.
- `agents/lead_agent.py::LeadAgent` — horizon-aware synthesis; persona prompt
  `irma_persona`; structured `Brief` + one JSON-parse retry. Pattern reused, not modified.
- `runtime/scheduler.py::Scheduler` — `AsyncIOScheduler` wrapper, currently only an
  `IntervalTrigger` observer refresh.
- `store/sqlite.py::SignalStore`, `store/repos/*` — repo pattern + migrations.

The existing `/api/v1/brief/*` GET endpoints and `LeadAgent` are **left intact** to
limit blast radius. The daily email is a new, parallel path.

## Architecture

```
8am cron tick ─┐
               ├─► DailyBriefService.build() ─► render_daily_email() ─► ResendSendTool.call()
POST /brief/email ─┘            │
   (Brief button)               ├─ re-run observers (fresh calendar)
                                ├─ SnapshotRepo: read baseline (latest date < today)
                                ├─ gather projects / today focus / 3-day lookahead (tasks ∪ calendar)
                                ├─ compute ProgressDelta (current − baseline)
                                ├─ LLM call (irma_persona + irma_daily_email composer)
                                └─ SnapshotRepo: upsert today's snapshot (next baseline)
```

### Component 1 — Daily snapshots (data)

New table `daily_snapshot`, one row per calendar day (upserted):

| column | type | notes |
|---|---|---|
| `snapshot_date` | TEXT (ISO date) | PRIMARY KEY |
| `per_project_counts` | TEXT (JSON) | `{project_id: {"open": int, "done": int}}` |
| `completed_task_ids` | TEXT (JSON) | list of task ids done as of this snapshot |
| `created_at` | TEXT (ISO datetime) | |

`store/repos/snapshot_repo.py::SnapshotRepo`:
- `async upsert(date, per_project_counts, completed_task_ids) -> None`
- `async latest_before(date) -> DailySnapshot | None` (baseline)
- `async get(date) -> DailySnapshot | None`

Migration appended to the existing migration set (see `tests/test_migrations.py`).

**Progress semantics:** baseline = `latest_before(today)`. Delta is computed against
that, *not* against today's row — so an on-demand re-send later in the day shows the
same day-over-day progress as the 8am send. First-ever run (no baseline) →
"no prior baseline yet" with absolute counts only.

### Component 2 — Models (`models/daily_brief.py`)

```python
class ProjectProgress(BaseModel):
    project_id: str
    project_name: str
    completed_since: int      # |today.completed_task_ids − baseline.completed_task_ids| for this project
    added_since: int          # (open_now + done_now) − (open_base + done_base), floored at 0
    open_now: int
    done_now: int
    note: str = ""            # LLM may annotate; default empty

class LookaheadItem(BaseModel):
    kind: Literal["task", "event"]
    title: str
    when: str                 # ISO date or datetime string
    project_name: str | None = None
    detail: str = ""

class DailyBrief(BaseModel):
    generated_at: datetime
    narrative: str            # LLM, Irma voice
    recommendation: str       # LLM
    conflicts: list[str]      # LLM
    progress: list[ProjectProgress]   # computed
    today_focus: list[FocusItem]      # computed (reuse models/brief.py FocusItem)
    lookahead: list[LookaheadItem]    # computed
    has_baseline: bool
```

The LLM only produces `narrative` / `recommendation` / `conflicts` (small JSON,
same fenced-JSON + one-retry parse pattern as `LeadAgent`). Everything factual is
computed in Python and *also* passed into the prompt as context.

### Component 3 — `DailyBriefService` (`agents/daily_brief.py`)

Constructed with `settings`, `llm: LLMClient`, `store: SignalStore`, and a
`calendar: ReadCalendarTool | None`, plus the observer list for the pre-refresh.

`async def build() -> DailyBrief`:
1. Re-run observers (`run_refresh`) so calendar signals are current — this absorbs
   the old Refresh button's responsibility.
2. Load active projects + open tasks (via `ProjectRepo` / `TaskRepo`).
3. **Today focus**: open tasks scheduled for / due today → `FocusItem`s.
4. **Lookahead** (`today … today + irma_brief_lookahead_days`): task
   `due_date`/`scheduled_for` in window ∪ calendar events from `ReadCalendarTool`
   (degrade to empty + a `conflicts`-adjacent note if OAuth absent).
5. **Progress**: `ProgressDelta` from `SnapshotRepo.latest_before(today)`.
6. Compose user message (new `irma_daily_email` prompt template) embedding progress
   + today focus + lookahead; system = `irma_persona`; call `llm.complete`; parse
   the small JSON (`narrative`/`recommendation`/`conflicts`) with one retry.
7. `SnapshotRepo.upsert(today, …)`.
8. Return `DailyBrief`.

### Component 4 — Email rendering (`agents/email_render.py`)

`render_daily_email(brief: DailyBrief, today: date) -> tuple[str, str]` → deterministic
plain text. Sections, each hidden when empty:

- Subject: `Irma · Daily Brief — {today:%a %d %b}`
- Body: narrative → **Progress since your last brief** (per-project deltas; or a
  "first brief" line when `not has_baseline`) → **Today's focus** → **Next 3 days**
  (deadlines + events) → **Heads-up** (conflicts) → recommendation.

Pure function, fully unit-testable.

### Component 5 — Scheduling

Extend `runtime/scheduler.py::Scheduler` with:

```python
def add_daily_job(self, callback, *, hour: int, timezone: str) -> None:
    self._sched.add_job(callback, trigger=CronTrigger(hour=hour, minute=0, timezone=timezone),
                        id="irma-daily-brief", replace_existing=True,
                        max_instances=1, coalesce=True)
```

Registered in `app.py` lifespan when `irma_daily_brief_enabled` and both LLM and the
Resend tool are available. The tick callback:
1. Guard: skip if in-memory `last_sent_date == today_local` (prevents a restart at
   08:00:30 from double-firing). **Strict**: no catch-up logic — the cron simply
   won't fire if the process wasn't running at 8am.
2. `DailyBriefService.build()` → `render_daily_email()` → `ResendSendTool.call()`.
3. Set `last_sent_date = today_local`. Publish `AgentState` thinking→idle around the call.

### Component 6 — On-demand send (API)

`POST /api/v1/brief/email` (added to `routers/brief.py`):
- 503 if `lead`-equivalent LLM or the Resend tool isn't configured (mirror the
  existing 503 pattern).
- Otherwise build → render → send. Returns `{"message_id": "..."}`.
- **Bypasses** the idempotency guard (always re-sends). Does not alter the cron's
  `last_sent_date` baseline semantics (snapshot baseline is date-keyed, so re-sends
  are consistent).

`apps/desktop/src/lib/api.ts`: add `sendBriefEmail(): Promise<{ message_id: string }>`;
remove the now-dead `fetchBrief`.

### Component 7 — Frontend

`apps/desktop/src/main/App.tsx`:
- Drop the `brief` tab from `Tab` union + nav; remove `BriefView` import/usage,
  `brief`/`briefBusy`/`briefError` state and the fetch-on-mount/synth effects.
- Replace the Refresh icon button with a **Brief** button (mail icon from
  `lib/icons.tsx`) wired to `sendBriefEmail()`, with `idle / sending / sent ✓ / error`
  states. Remove the now-unused `forceRefresh` import + `refresh` handler.

Delete `apps/desktop/src/main/brief/BriefView.tsx` (dead after the tab removal).
Add a `MailIcon` to `lib/icons.tsx`.

### Component 8 — Config (`config.py` + `.env.example`)

| setting | default |
|---|---|
| `irma_daily_brief_enabled` | `True` |
| `irma_brief_timezone` | `"Asia/Jerusalem"` |
| `irma_brief_hour` | `8` |
| `irma_brief_lookahead_days` | `3` |

## Testing (TDD)

- `SnapshotRepo` round-trip + `latest_before` + upsert idempotency; migration applies.
- Progress-delta computation (completed/added/open/done; no-baseline path).
- 3-day lookahead window: tasks ∪ calendar, correct boundary `[today, today+3]`.
- `DailyBriefService.build()` with a fake LLM + fake calendar: asserts snapshot written,
  prompt embeds progress/lookahead, JSON parsed (incl. one-retry path).
- `render_daily_email()` formatting: section presence/omission, subject, no-baseline line.
- `POST /brief/email`: 503 unconfigured; 200 + `message_id` with fakes.
- `Scheduler.add_daily_job` registers a `CronTrigger` at hour=8 `Asia/Jerusalem`;
  tick idempotency guard skips a same-day second fire.

## Out of scope / non-goals

- No HTML email (Resend tool sends plain text; persona voice carries it).
- No startup catch-up for missed 8am (strict — explicit decision).
- Existing `/brief/*` GET endpoints + `LeadAgent` unchanged.
- No per-task diff narrative beyond counts + completed list (per-project delta only).
