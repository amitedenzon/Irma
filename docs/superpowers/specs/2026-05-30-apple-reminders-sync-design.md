# Apple Reminders Two-Way Sync — Design

**Date:** 2026-05-30
**Goal:** Mirror Irma's Projects and Tasks into native macOS Reminders lists (one per Project, name-prefixed `Irma · `) so the user can view, complete, edit, and quick-capture from their iPhone via iCloud sync. Full peer sync — edits flow both directions.

> **Amendment 2026-05-30 (afternoon): one-calendar-per-project.** The original spec mapped Project → parent reminder, Task → subtask of project. Verification against the macOS 15.x / 26.x EventKit headers confirmed `EKReminder.parentReminder` and any subtask-parent property are NOT in the public API — Apple's own Reminders.app uses a private framework extension. Third-party EventKit cannot create or read parent/child relationships. The spec is therefore restructured: **each Project maps to its own `EKCalendar` (reminders list), named `Irma · <ProjectName>`. Tasks are flat reminders in their project's calendar.** All "parent reminder" references below have been rewritten to reflect this; the original wording is preserved in commit history.

## Problem

Irma's PMO surface (Projects + Tasks) lives only in the desktop app. The user wants the same data on iPhone for in-the-moment task review and capture. Building a native iOS app is out of scope; the pragmatic substitute is to surface Irma data through Apple Reminders, which already syncs to iPhone via iCloud.

Per `CLAUDE.md`, this is Phase 5 work ("Outbound channels") pulled forward.

## Decision

1. Mirror Irma's data into **one macOS Reminders list per Project**, each named `Irma · <ProjectName>`. The Inbox is `Irma · Inbox`. Multiple lists in the sidebar is the accepted cost of using native EventKit subtask semantics being unavailable.
2. **Project = an `EKCalendar`** (reminders list). **Task = a flat `EKReminder`** in that project's calendar. No parent/child relationships are used — they aren't in the public API.
3. **Full peer sync**: edits in either direction propagate. Conflicts resolved by last-write-wins on `Task.updated_at` vs `EKReminder.lastModifiedDate`.
4. Phone-initiated **reminders captured in `Irma · Inbox`** become Tasks in the Inbox Project. Reminders the user adds to any `Irma · X` list become Tasks in Project X. Reminders in lists NOT prefixed with `Irma · ` are ignored.
5. Bridge to EventKit via a small **Swift helper binary** (`irma-reminders-helper`) invoked as a subprocess. Helper holds the stable TCC permission identity; survives venv rebuilds.
6. New branch off `main`. Independent of `feat/chat-tools-parity`.

## Out of scope

- Live EventKit change notifications. 60-second poll is sufficient.
- Sub-subtasks (Irma's model is flat at the task level).
- Sync of Project metadata beyond `name` (`description`, `goals`, `target_date`, `calendar_keywords`, `priority` stay Irma-only).
- Sync of `Task.estimated_minutes` (Irma-only).
- Mapping for `status=BLOCKED` and `status=DOING` (collapsed to "open" on phone).
- A recoverable trash. Phone-delete is a permanent delete in Irma.
- macOS notifications when the phone changes something (separate Phase 5 feature).
- Tauri-side code signing for the helper in production. Local unsigned build works for MVP; signing folds into the existing Tauri release recipe later.
- A chat tool wrapper (`list_reminders`, `force_sync_reminders`). Easy to add on top of the bridge later; not required for the core feature.

## Architecture

```
                  ┌────────────────────────────────────────┐
                  │             FastAPI process            │
                  │                                        │
   API request ──▶│  ReminderSyncService                   │
                  │     │                                  │
                  │     ├──▶ ProjectRepo / TaskRepo  ◀── SQLite
                  │     │                                  │
                  │     └──▶ ReminderBridge (asyncio.subprocess)
                  └────────────────│───────────────────────┘
                                   ▼
                       irma-reminders-helper  (Swift CLI)
                                   │
                                   ▼  EventKit
                       ┌────────────────────────┐
                       │  macOS Reminders DB    │ ◀── iCloud ──▶  iPhone
                       └────────────────────────┘
```

### Components

- **`ReminderBridge`** — `services/api/src/irma_api/integrations/reminders/bridge.py`. Thin async wrapper over the helper binary. Each method spawns one subprocess via `asyncio.create_subprocess_exec`, writes JSON on stdin, reads JSON on stdout, raises `BridgeError` on non-zero exit or non-JSON output.
- **`ReminderSyncService`** — `services/api/src/irma_api/integrations/reminders/sync.py`. Owns the reconciliation logic. Exposes a single coroutine `sync_once()`. Guarded by an `asyncio.Lock` so overlapping triggers coalesce.
- **Swift helper** — `tools/reminders-helper/`. Standalone Swift package, ~250 lines. Build output is a universal binary (`arm64;x86_64`) checked in at `tools/reminders-helper/bin/irma-reminders-helper`. CI rebuilds on the macOS runner and verifies the checked-in artifact.
- **New router** — `services/api/src/irma_api/routers/reminders.py`. Endpoints: `POST /integrations/reminders/link`, `DELETE /integrations/reminders/link`, `POST /integrations/reminders/sync`, and a `reminders_*` extension to the existing `/integrations/google/status` response.
- **Scheduler tick** — `services/api/src/irma_api/runtime/scheduler.py`. APScheduler job, every 60 s, only runs when the integration is linked. Skipped while the lock is held.
- **Linkage columns** — `Project.reminder_calendar_id TEXT NULL UNIQUE` (an `EKCalendar.calendarIdentifier`) and `Task.reminder_uuid TEXT NULL UNIQUE` (an `EKReminder.calendarItemIdentifier`). Together they form the join key between Irma's DB and EventKit.
- **Settings** — extend `config.py` with `reminders_linked: bool = False` (set on successful link), `reminders_sync_interval_seconds: int = 60`, `reminders_helper_path: Path`. The legacy `reminders_calendar_id` is gone — there is no single calendar.

### Sync triggers

| Trigger | Where | Behavior |
| --- | --- | --- |
| Periodic | `runtime/scheduler.py` | every 60 s while integration is linked |
| Irma-side write | `routers/projects.py`, `routers/tasks.py` | after successful commit, fire-and-forget `asyncio.create_task(sync.sync_once())` |
| Manual | `POST /integrations/reminders/sync` | awaits result; for dashboard "Sync now" button |
| Initial link | `POST /integrations/reminders/link` | runs `sync_once()` once after permission grant |

**Coalescing rule (applies to all triggers):** the service holds an `asyncio.Lock` plus a single `pending_rerun: bool` flag. If `sync_once()` is invoked while a sync is in progress, the flag is set and the call returns immediately. When the in-flight sync finishes, it checks the flag and, if set, kicks one follow-up sync. This guarantees the last write always lands within at most one extra cycle, without unbounded queueing.

## Data model and field mapping

### Identity tree

```
Reminders sidebar:
   ├─ Irma · Inbox                  ← EKCalendar; the Inbox project
   │     ├─ EKReminder (Task)
   │     └─ EKReminder (Task)
   ├─ Irma · Video Model            ← EKCalendar; one project
   │     ├─ EKReminder (Task)
   │     └─ EKReminder (Task)
   ├─ Irma · MIT Deep Learning      ← EKCalendar; another project
   │     └─ EKReminder (Task)
   └─ <user's other unrelated lists, ignored>
```

**Calendar naming.** Every Irma-owned calendar starts with the literal prefix `Irma · ` (capital-I, ASCII space, U+00B7 middle dot, ASCII space). Calendars not matching that prefix are completely ignored by the sync. The trailing portion after the prefix is the project's `name`.

**Inbox.** A regular `Project` row seeded on first link (`name="Inbox"`, `status=active`, `goals=[]`, `description="Auto-created. Triage items captured from phone."`) with a paired calendar `Irma · Inbox`. If the user deletes either side, the next sync recreates it.

### Task field mapping

| Irma `Task` | Reminder field | Direction | Notes |
| --- | --- | --- | --- |
| `title` | `title` | ↔ both | trimmed |
| `notes` | `notes` | ↔ both | direct |
| `due_date` | `dueDateComponents` (date-only) | ↔ both | no time component |
| `scheduled_for` | `startDateComponents` (date-only) | ↔ both | makes iOS "Today" smart list useful |
| `status=done` | `isCompleted=true`, `completionDate` | ↔ both | flip in either direction |
| `status=todo`/`doing`/`blocked` | `isCompleted=false` | Irma → Reminders write-only | phone sees all three as "open"; toggling-uncomplete from phone resets Irma to `todo` |
| `estimated_minutes` | — | Irma-only | not visible on phone |
| `project_id` | which `EKCalendar` the reminder lives in | ↔ both | moving a reminder to a different `Irma · <X>` list on phone re-attributes the Task to Project X |
| `id` (Irma) | — | Irma-only | linkage is `reminder_uuid` |
| `updated_at` | `lastModifiedDate` | derived | used for conflict resolution |

### Project field mapping

| Irma `Project` | Reminder field | Direction | Notes |
| --- | --- | --- | --- |
| `name` | `EKCalendar.title` minus the `Irma · ` prefix | ↔ both | renaming the calendar on phone renames the Project, *if* the new name still starts with `Irma · `. A user-initiated rename that drops the prefix means "stop syncing this list" — see below. |
| `description`, `goals`, `target_date`, `calendar_keywords`, `priority` | — | Irma-only | the calendar carries only the title |
| `status=archived` | calendar deleted from Reminders (with all its reminders) | Irma → Reminders | clean phone view; archive lives in Irma DB |
| `status=paused` | calendar kept; `title` becomes `Irma · ⏸ <name>` | Irma → Reminders | visible on phone with pause emoji; still tappable |
| `reminder_calendar_id` | `EKCalendar.calendarIdentifier` | linkage | stored on the Project row; stable across renames |

**Renaming and reparenting rules.**
- User renames `Irma · X` to `Irma · Y` on phone → Irma renames Project X to Y on next sync (`name` field updated).
- User renames `Irma · X` to anything without the `Irma · ` prefix on phone → next sync treats it as "user unlinked this project" and clears `reminder_calendar_id` on the Project row, then leaves the now-orphaned list alone. The Project still exists in Irma; it'll get a fresh `Irma · X` calendar created on the following sync. The user can re-link by renaming the orphan list back.
- User moves a reminder from `Irma · A` to `Irma · B` on phone → Irma's planner sees the reminder's calendar identifier changed, looks up the new calendar's linked Project, and reattributes the Task via `project_id` update.

### Phone-initiated semantics

- **Reminder added to `Irma · X` list on phone** → new `Task` row, `project_id` set to Project X.
- **Reminder added to `Irma · Inbox`** → new `Task` row in the Inbox project.
- **Reminder added to a non-`Irma · *` list** → ignored entirely. Not Irma's concern.
- **New `Irma · X` list created on phone (no matching Project)** → *not* auto-promoted to a Project. Projects are created in Irma only; the orphan list is ignored. (Recover by creating Project X in Irma; the next sync will see the existing matching calendar and link it.)
- **Deleting a reminder on phone** → corresponding Irma `Task` row is **deleted**. No tombstone.
- **Deleting an `Irma · X` calendar on phone** → next sync detects `reminder_calendar_id` invalid; if Project X has `status=active`, recreates the calendar and re-pushes its tasks. If `status=archived`, leaves it gone.
- **Renaming `Irma · X` to `Irma · Y`** → renames Project X to Y in Irma DB.
- **Renaming `Irma · X` to anything without the `Irma · ` prefix** → effectively unlinks: Irma clears `reminder_calendar_id` on the Project, leaves the orphan list alone, and will create a fresh `Irma · X` calendar on the next sync.

### Conflict resolution

Last-write-wins. Compare `Task.updated_at` (or `Project.updated_at`) against the helper-reported `lastModifiedDate`. Loser is overwritten in place. NTP-synced clocks via iCloud make drift negligible; we do not try to harden this further.

## Sync engine

A single `ReminderSyncService.sync_once()` coroutine is the only place that touches both sides. All triggers funnel into it.

### Algorithm — four passes

1. **Calendar reconcile.** Enumerate calendars on both sides:
   - Irma: every Project (any status). Each has optional `reminder_calendar_id`.
   - Reminders: `helper list-calendars --prefix "Irma · "`. Returns `[{calendar_id, title}, ...]` for every list whose title begins with the prefix.

   Match by `calendar_id` (preferred) or by name (`Irma · <Project.name>`). Plan calendar mutations:
   - Project active, no `reminder_calendar_id` set, no matching name on phone → `ensure-list` with `Irma · <name>`; store the returned id.
   - Project active, has `reminder_calendar_id` but the id is gone on phone → user deleted the list. Re-`ensure-list` and re-push the project's tasks (next pass).
   - Project active, has `reminder_calendar_id`, calendar title changed → if still prefixed `Irma · X`, rename `Project.name` to X (phone wins on rename). If prefix dropped, clear `reminder_calendar_id` (phone unlinked) — Project remains active and gets a fresh calendar next sync.
   - Project archived → delete the calendar (if linked).
   - Project paused → rename the calendar to `Irma · ⏸ <name>` (no-op if already matching).
   - `Irma · X` calendar on phone with no matching Project → ignored (logged at debug). User can adopt it by creating Project X in Irma later.

2. **Per-project reminder snapshot.** For each linked `(Project, calendar_id)` pair, run `helper list --calendar-id <id>` to snapshot its reminders. The Inbox project is included like any other.

3. **Reminder reconcile.** Per project, build a `SyncPlan` segment:
   - `irma_tasks_by_uuid: dict[reminder_uuid, IrmaTask]` (only this project's tasks with `reminder_uuid` set).
   - `rem_by_uuid: dict[uuid, HelperReminder]` (this project's calendar).

   Classification:

   ```
   Irma has, Reminders has    → diff updated_at vs lastModifiedDate → patch loser
   Irma has, Reminders missing → CREATE in this calendar
   Reminders has, Irma missing → CREATE on Irma side, project_id = this Project's id
   ```

   Cross-calendar task moves: if a `reminder_uuid` shows up in calendar A's snapshot but Irma has it linked to a Project whose calendar is B, the planner updates `Task.project_id` to A's owning Project.

4. **Apply.** One `batch` invocation per affected calendar. Each result carries the new `lastModifiedDate`. Write-back:
   - `reminder_uuid` onto any newly-created Irma Task rows.
   - `reminder_calendar_id` onto any newly-created/relinked Project rows.
   - `Task.updated_at` = the result's `last_modified` for every touched task — prevents bounce on the next tick.
   - `Project.updated_at` bumped whenever the calendar was renamed or linked.

### Idempotency

Every op is keyed by stable identifier (`reminder_uuid` on the Reminders side, `Task.id` / `Project.id` on the Irma side). Re-running a partially-applied sync is safe.

### Error handling

| Failure | Behavior |
| --- | --- |
| TCC denied | Helper exits with `{"error": "access_denied"}`. `AgentState=alert`, status endpoint reports the failure, no retry. User must click "Link" again to re-prompt. |
| Project's calendar deleted on phone | Detected in pass 1 by `reminder_calendar_id` no longer appearing in `list-calendars`. Re-`ensure-list` and re-push the project's tasks. One-tick alert state. |
| Helper crashes or non-JSON output | Wrap as `BridgeError`, log via `structlog`, `AgentState=alert`, skip this tick, retry on next. |
| Partial batch failure | `--continue-on-error`; per-op result reported. Failed ops are logged and retried next tick. Successful ones commit. |
| iCloud not signed in | Local Reminders DB still works. We don't try to verify iCloud is up. Outside our control. |

## Permissions and linking flow

### TCC constraints

- macOS 14+ requires `requestFullAccessToReminders` for read+write.
- Permission grants are tied to the *code-signed identity* of the binary calling EventKit. The Swift helper exists precisely so the grant is stable across `uv` venv rebuilds and Python upgrades.
- The helper binary embeds `NSRemindersUsageDescription` in its Mach-O `__TEXT,__info_plist` section at link time. Without it, macOS suppresses the permission dialog and the call silently fails.
- For dev (unsigned), macOS keys the grant by path; for production (signed in the Tauri release), it keys by signature. Same code, different identity envelope.

### Linking flow

1. Dashboard sees `reminders_linked: false` on `GET /integrations/google/status`.
2. User clicks "Link Reminders" → `POST /integrations/reminders/link`.
3. Server spawns `helper request-access`. macOS shows the system dialog. User clicks Allow.
4. Helper returns `{"granted": true}`.
5. Server flips `settings.reminders_linked = true` (in-memory; persisted via the integrations status endpoint).
6. Server triggers a full `sync_once()`, which:
   - Calls `ensure_inbox_project()` to seed the Inbox Project row if missing.
   - Runs the calendar-reconcile pass — `ensure-list` is invoked once per active Project (including Inbox), creating `Irma · <name>` lists that don't already exist; storing each `calendar_id` on the Project row.
   - Pushes every active Project's tasks into its calendar.
7. Status endpoint now reports `reminders_linked: true` plus per-Project linkage state.

Calendar identifiers are stable across phone-side renames; only deletion invalidates them.

### Unlink

`DELETE /integrations/reminders/link`:
- Clears `reminder_uuid` from every Task row.
- Clears `reminder_calendar_id` from every Project row.
- Sets `reminders_linked=false`.
- **Does not** delete the Reminders lists themselves (user's data, their call). A separate UI affordance can offer that later.
- Re-linking later runs the calendar-reconcile pass against the existing `Irma · *` calendars on phone, matching them to Projects by name and adopting them non-destructively.

## Swift helper command surface

All commands accept JSON on stdin where applicable, write JSON to stdout, exit non-zero with `{"error": "<code>", "message": "..."}` on stderr.

| Command | Stdin | Stdout | Purpose |
| --- | --- | --- | --- |
| `request-access` | — | `{"granted": bool, "reason"?: string}` | trigger TCC prompt |
| `access-status` | — | `{"status": "authorized" \| "denied" \| "restricted" \| "notDetermined"}` | check without prompting |
| `ensure-list --name <s>` | — | `{"calendar_id": "<EKCalendar.calendarIdentifier>"}` | create-or-find (used per project) |
| `list-calendars --prefix <s>` | — | `{"calendars": [{"calendar_id": "...", "title": "..."}, ...]}` | enumerate every reminders calendar whose title starts with `<prefix>`; the planner uses this to discover phone-side calendar adds/renames/deletes |
| `list --calendar-id <s>` | — | `{"reminders": [...]}` | full snapshot of one calendar's reminders |
| `batch --calendar-id <s> --continue-on-error` | `{"ops": [{"op":"create","fields":{...}}, {"op":"update","uuid":"...","fields":{...}}, {"op":"delete","uuid":"..."}]}` | `{"results": [{"index": 0, "ok": true, "uuid": "...", "last_modified": "<iso8601>"}, ...]}` (delete ops omit `last_modified`) | mutate one calendar |
| `rename-calendar --calendar-id <s> --title <s>` | — | `{"renamed": bool}` | rename an existing calendar (used for pause/resume and for keeping the Irma-prefix in sync) |
| `delete-calendar --calendar-id <s>` | — | `{"deleted": bool}` | used by archive flow + explicit unlink path |

The wire schema for one reminder has no `parent_uuid` field — the post-amendment design doesn't use parent/child relationships. `ReminderFields` likewise drops `parent_uuid`.

## Settings additions

```python
# config.py
reminders_linked: bool = False                       # set true after a successful link
reminders_calendar_prefix: str = "Irma · "           # all managed lists start with this
reminders_sync_interval_seconds: int = 60            # poll cadence
reminders_helper_path: Path = Path("tools/reminders-helper/bin/irma-reminders-helper")
```

No OAuth, no API keys, no `.env` entries required. Single-tenant local resource.

## Database migrations

One additive migration in `services/api/src/irma_api/store/migrations.py`:

- Add `reminder_uuid TEXT NULL UNIQUE` to `task` (an `EKReminder.calendarItemIdentifier`).
- Add `reminder_calendar_id TEXT NULL UNIQUE` to `project` (an `EKCalendar.calendarIdentifier`).

Both as partial-unique indexes (`WHERE column IS NOT NULL`) so `NULL` rows don't collide. No data backfill — `NULL` is the correct unlinked state.

## API surface additions

Extend `routers/integrations.py::IntegrationsStatus`:

```python
class IntegrationsStatus(BaseModel):
    calendar_linked: bool
    resend_linked: bool
    reminders_linked: bool                          # new
    reminders_last_sync_at: datetime | None         # new
    reminders_last_sync_error: str | None           # new
    user_email: str | None
    llm_backend: str | None
    llm_model: str | None
```

New `routers/reminders.py`:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/integrations/reminders/link` | trigger TCC prompt, ensure list, initial sync |
| DELETE | `/api/v1/integrations/reminders/link` | clear linkage; preserve the Reminders list itself |
| POST | `/api/v1/integrations/reminders/sync` | force a sync now; returns counts |

## Observability

- All sync ops emit `structlog` events: `reminders.sync.started`, `reminders.sync.completed` (with `created_remote`, `updated_remote`, `created_local`, `updated_local`, `deleted_remote`, `deleted_local`, `conflicts`), `reminders.sync.failed` (with error code).
- `AgentState=alert` flips on: TCC denied, helper crash, missing list (during the brief window before recreate), or batch with >50% failure rate. Sprite reacts.
- `reminders_last_sync_at` and `reminders_last_sync_error` surfaced on the integrations status endpoint for the dashboard.

## Testing strategy

EventKit cannot be mocked from Python and CI runners do not have a Reminders database. The split:

1. **Sync engine unit tests** — `services/api/tests/integrations/test_reminders_planner.py`. The reconciliation `plan(irma, helper_calendars_with_reminders) -> SyncPlan` is a pure function. Hand-crafted inputs cover each branch: project-needs-calendar, calendar-rename-on-phone-renames-project, prefix-dropped-on-phone-unlinks-project, task-both-sides-match, task-irma-only, task-remote-only-into-its-project, conflict-by-timestamp, cross-calendar-task-move, paused-project-prefix-rename, archived-project-deletes-calendar. No subprocess, no async, instant.
2. **Bridge tests with fake helper** — `services/api/tests/integrations/test_reminders_bridge.py`. Replace the helper binary path with `tests/fixtures/fake_helper.py`, a Python script speaking the same JSON protocol against an in-memory dict. Validates command serialization, JSON parsing, error-code surfacing, non-JSON output handling. Runs anywhere; no macOS dependency.
3. **End-to-end smoke test, opt-in only** — `services/api/tests/integrations/test_reminders_e2e.py`, marked `@pytest.mark.skipif(not os.environ.get("IRMA_REMINDERS_E2E"))`. Uses the real helper against the real Reminders DB, creates a temp list (`Irma-Test-<uuid>`), runs sync, asserts, tears down. Documented in the README as `IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py`. Never runs in CI.
4. **Swift helper tests** — `tools/reminders-helper/Tests/`. Standard XCTest, `swift test`. CI runs them on the macOS runner because the helper binary artifact is checked in.

## Risks

| Risk | Mitigation |
| --- | --- |
| User clicks Deny on the TCC dialog | Status surface includes the explicit path to System Settings → Privacy → Reminders. "Link Reminders" button re-prompts on next click only if status is `notDetermined`. |
| Helper binary code-signing for production Tauri | Folds into the existing Developer ID signing recipe for the Tauri app. Out of scope for MVP. |
| iCloud not signed in on user's Mac | Sync still works against the local Reminders DB; iCloud propagation is the user's concern. We surface no error. |
| User renames `Irma · X` to `Irma · Y` on phone | Phone wins — Project X renamed to Y on next sync. |
| User renames `Irma · X` to drop the prefix on phone | Treated as unlink: `reminder_calendar_id` cleared, orphan list left alone, fresh `Irma · X` calendar created next sync. |
| User deletes an `Irma · X` calendar on phone | Project still active → recreated and re-pushed on next tick (one-tick alert). Project archived → stays gone. |
| User creates an `Irma · X` calendar on phone with no matching Project | Ignored. To adopt, create Project X in Irma; next sync links the existing calendar. |
| Many projects clutter the Reminders sidebar | Accepted trade-off; user opted into one-list-per-project after the parent-reminder API was found missing. Mitigation idea (deferred): allow archiving a project without deleting its phone list, just unlink. |
| Clock skew between Mac and phone | Negligible (NTP via iCloud); explicit non-goal. |
| `BLOCKED` / `DOING` lossiness on phone | Documented; implied by the "full peer" decision. |
| User renames the Inbox project in Irma | It becomes a normal Project; sync seeds a fresh "Inbox" Project + `Irma · Inbox` calendar on next tick. |

## Implementation phases

Suggested implementation slicing (real plan comes from `writing-plans`):

1. Swift helper: subcommand surface + XCTest.
2. `ReminderBridge` + fake helper + bridge tests.
3. Schema migration (`reminder_uuid` columns).
4. `ReminderSyncService` reconciliation logic + unit tests.
5. Router (`/integrations/reminders/{link,sync}`) + status extension.
6. Scheduler job + Irma-side write triggers.
7. Frontend "Link Reminders" affordance on the integrations panel.
8. Opt-in e2e smoke test, README updates.
