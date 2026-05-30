# Apple Reminders Two-Way Sync — Design

**Date:** 2026-05-30
**Goal:** Mirror Irma's Projects and Tasks into a single macOS Reminders list named "Irma" so the user can view, complete, edit, and quick-capture from their iPhone via iCloud sync. Full peer sync — edits flow both directions.

## Problem

Irma's PMO surface (Projects + Tasks) lives only in the desktop app. The user wants the same data on iPhone for in-the-moment task review and capture. Building a native iOS app is out of scope; the pragmatic substitute is to surface Irma data through Apple Reminders, which already syncs to iPhone via iCloud.

Per `CLAUDE.md`, this is Phase 5 work ("Outbound channels") pulled forward.

## Decision

1. Mirror Irma's data into one macOS Reminders list called **"Irma"**.
2. Each **Project = a parent reminder** in that list; each **Task = a subtask** of its project parent. EventKit does not expose iOS 17 "Sections" as a first-class API — parent/subtask is the only viable way to render "project as a topic" within one list.
3. **Full peer sync**: edits in either direction propagate. Conflicts resolved by last-write-wins on `Task.updated_at` vs `EKReminder.lastModifiedDate`.
4. Phone-initiated **orphan reminders** (created at the top of the list with no parent) are pulled into an auto-managed **"Inbox" Project**.
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
- **Linkage columns** — `Task.reminder_uuid TEXT NULL UNIQUE` and `Project.reminder_uuid TEXT NULL UNIQUE`. The join key between Irma's DB and EventKit's `calendarItemIdentifier`.
- **Settings** — extend `config.py` with `reminders_calendar_id: str | None`, `reminders_sync_interval_seconds: int = 60`, `reminders_helper_path: Path`.

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
EKCalendar("Irma")                          ← managed; auto-created if missing
   ├─ EKReminder (project parent)           ← reminder_uuid stored on Project row
   │     ├─ EKReminder (subtask = Task)     ← reminder_uuid stored on Task row
   │     └─ EKReminder (subtask = Task)
   ├─ EKReminder (project parent)
   └─ EKReminder ("Inbox")                  ← reserved parent for orphan capture
         ├─ EKReminder (orphan from phone)  ← becomes Task in project "Inbox"
         └─ ...
```

The "Inbox" Project is a regular `Project` row seeded on first link (`name="Inbox"`, `status=active`, `goals=[]`, `description="Auto-created. Triage items captured from phone."`). No model-level distinction. If the user deletes it, the next sync recreates it because the orphan handler needs a parent.

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
| `project_id` | parent reminder | ↔ both | re-parenting a subtask on phone re-attributes the Task in Irma |
| `id` (Irma) | — | Irma-only | linkage is `reminder_uuid` |
| `updated_at` | `lastModifiedDate` | derived | used for conflict resolution |

### Project field mapping

| Irma `Project` | Reminder field | Direction | Notes |
| --- | --- | --- | --- |
| `name` | parent reminder `title` | ↔ both | renaming the parent on phone renames the Project |
| `description`, `goals`, `target_date`, `calendar_keywords`, `priority` | — | Irma-only | parent reminder is name-only on phone |
| `status=archived` | parent + all subtasks deleted from Reminders | Irma → Reminders | clean phone view; archive lives in Irma DB |
| `status=paused` | parent reminder kept, `title` prefixed with `⏸ ` | Irma → Reminders | distinct on phone, still tappable |

### Phone-initiated semantics

- **Subtask added under a project parent** → new `Task` row, `project_id` = that project's id.
- **Top-level reminder in the Irma list** → `Task` row in the "Inbox" Project.
- **New top-level reminder whose title matches an existing project name** → *not* auto-promoted to a Project. Projects are created in Irma only.
- **Deleting a reminder on phone** → corresponding Irma row is **deleted**. No tombstone, no recoverable trash.
- **Deleting the entire "Irma" calendar on phone** → next sync detects the id is invalid, recreates the list, re-pushes from Irma DB, flips `AgentState=alert` for one tick.

### Conflict resolution

Last-write-wins. Compare `Task.updated_at` (or `Project.updated_at`) against the helper-reported `lastModifiedDate`. Loser is overwritten in place. NTP-synced clocks via iCloud make drift negligible; we do not try to harden this further.

## Sync engine

A single `ReminderSyncService.sync_once()` coroutine is the only place that touches both sides. All triggers funnel into it.

### Algorithm — three passes

1. **Snapshot.**
   - From Irma: every Project (any status) and every Task in one query, selecting only the syncable columns plus `id`, `reminder_uuid`, `updated_at`.
   - From Reminders: one helper invocation, `helper list --calendar-id <id> --json`. Returns an array of `{uuid, parent_uuid, title, notes, due, start, completed, completion_date, last_modified}`.

2. **Reconcile.** Build a `SyncPlan` (pure data; no mutations yet). Two indexes:
   - `irma_by_uuid: dict[reminder_uuid, IrmaRow]` — only rows whose `reminder_uuid` is set.
   - `rem_by_uuid: dict[uuid, HelperReminder]`.

   Classification:

   ```
   Irma has, Reminders has    → diff updated_at vs lastModifiedDate → patch loser
   Irma has, Reminders missing → CREATE on Reminders
   Reminders has, Irma missing → CREATE on Irma (orphan → Inbox if no parent match)
   ```

   Plan ordering:
   1. Project parents first (a Task CREATE needs its parent's uuid).
   2. Tasks second.
   3. Deletes last (a Task moved between projects shows up as a `parent_uuid` change before any delete fires).

3. **Apply.** One helper invocation per sync via the `batch` command — JSON array of `create`/`update`/`delete` ops in, JSON array of results out. Each result includes the new `lastModifiedDate` of the affected reminder. The service then writes back:
   - `reminder_uuid` onto any newly-created Irma rows.
   - `updated_at = <result.last_modified>` onto every Irma row touched by this sync — both rows patched *from* the phone side **and** rows whose Irma-side edit we just pushed up. Matching the timestamps prevents the next tick from seeing a spurious `lastModifiedDate > updated_at` and bouncing the same row.

### Idempotency

Every op is keyed by stable identifier (`reminder_uuid` on the Reminders side, `Task.id` / `Project.id` on the Irma side). Re-running a partially-applied sync is safe.

### Error handling

| Failure | Behavior |
| --- | --- |
| TCC denied | Helper exits with `{"error": "access_denied"}`. `AgentState=alert`, status endpoint reports the failure, no retry. User must click "Link" again to re-prompt. |
| "Irma" list missing on Reminders side | Helper's `ensure-list` runs at the top of every sync; one extra round-trip but bulletproof. |
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
5. Server calls `helper ensure-list --name Irma` → stores returned `calendar_id` in settings as `reminders_calendar_id`.
6. Server triggers a full `sync_once()`, pushing every existing active Project + Task into the new list.
7. Status response now reports `reminders_linked: true`.

The stored `calendar_id` survives renames on the phone (EKCalendar identifiers are stable); only deletion invalidates it.

### Unlink

`DELETE /integrations/reminders/link`:
- Clears `reminder_uuid` from every Project and Task row.
- Sets `reminders_linked=false`.
- **Does not** delete the Reminders list itself (user's data, their call). A separate UI affordance can offer that later.
- Re-linking later treats the existing reminders as "Reminders-only, create on Irma side"; orphans land in Inbox; re-link is non-destructive.

## Swift helper command surface

All commands accept JSON on stdin where applicable, write JSON to stdout, exit non-zero with `{"error": "<code>", "message": "..."}` on stderr.

| Command | Stdin | Stdout | Purpose |
| --- | --- | --- | --- |
| `request-access` | — | `{"granted": bool, "reason"?: string}` | trigger TCC prompt |
| `access-status` | — | `{"status": "authorized" \| "denied" \| "restricted" \| "notDetermined"}` | check without prompting |
| `ensure-list --name <s>` | — | `{"calendar_id": "<EKCalendar.calendarIdentifier>"}` | create-or-find |
| `list --calendar-id <s>` | — | `{"reminders": [...]}` | full snapshot of the calendar |
| `batch --calendar-id <s> --continue-on-error` | `{"ops": [{"op":"create","fields":{...}}, {"op":"update","uuid":"...","fields":{...}}, {"op":"delete","uuid":"..."}]}` | `{"results": [{"index": 0, "ok": true, "uuid": "...", "last_modified": "<iso8601>"}, ...]}` (delete ops omit `last_modified`) | the workhorse — one round-trip per sync |
| `delete-calendar --calendar-id <s>` | — | `{"deleted": bool}` | only used by an explicit destructive unlink path; not the default |

## Settings additions

```python
# config.py
reminders_calendar_id: str | None = None     # EKCalendar identifier, set on link
reminders_sync_interval_seconds: int = 60    # poll cadence
reminders_helper_path: Path = Path("tools/reminders-helper/bin/irma-reminders-helper")
```

No OAuth, no API keys, no `.env` entries required. Single-tenant local resource.

## Database migrations

One Alembic-equivalent migration in `services/api/src/irma_api/store/migrations.py`:

- Add `reminder_uuid TEXT NULL UNIQUE` to `task`.
- Add `reminder_uuid TEXT NULL UNIQUE` to `project`.

Indexes implied by `UNIQUE`. No data backfill — `NULL` is the correct unlinked state.

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

1. **Sync engine unit tests** — `services/api/tests/integrations/test_reminders_sync.py`. The reconciliation `plan(irma_rows, helper_reminders) -> SyncPlan` is a pure function. Hand-crafted inputs cover each branch: both-sides-match, Irma-only, Reminders-only, conflict-by-timestamp, parent re-attribution, orphan-into-Inbox, paused-project-prefix, archived-project-cascade-delete. No subprocess, no async, instant.
2. **Bridge tests with fake helper** — `services/api/tests/integrations/test_reminders_bridge.py`. Replace the helper binary path with `tests/fixtures/fake_helper.py`, a Python script speaking the same JSON protocol against an in-memory dict. Validates command serialization, JSON parsing, error-code surfacing, non-JSON output handling. Runs anywhere; no macOS dependency.
3. **End-to-end smoke test, opt-in only** — `services/api/tests/integrations/test_reminders_e2e.py`, marked `@pytest.mark.skipif(not os.environ.get("IRMA_REMINDERS_E2E"))`. Uses the real helper against the real Reminders DB, creates a temp list (`Irma-Test-<uuid>`), runs sync, asserts, tears down. Documented in the README as `IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py`. Never runs in CI.
4. **Swift helper tests** — `tools/reminders-helper/Tests/`. Standard XCTest, `swift test`. CI runs them on the macOS runner because the helper binary artifact is checked in.

## Risks

| Risk | Mitigation |
| --- | --- |
| User clicks Deny on the TCC dialog | Status surface includes the explicit path to System Settings → Privacy → Reminders. "Link Reminders" button re-prompts on next click only if status is `notDetermined`. |
| Helper binary code-signing for production Tauri | Folds into the existing Developer ID signing recipe for the Tauri app. Out of scope for MVP. |
| iCloud not signed in on user's Mac | Sync still works against the local Reminders DB; iCloud propagation is the user's concern. We surface no error. |
| User renames the "Irma" list on phone | Survives — we store `calendar_id`, not name. |
| User deletes the "Irma" list on phone | Detected on next tick; list recreated, data re-pushed from Irma DB; one-tick alert state. |
| Clock skew between Mac and phone | Negligible (NTP via iCloud); explicit non-goal. |
| `BLOCKED` / `DOING` lossiness on phone | Documented; implied by the "full peer" decision. |
| User renames the Inbox project in Irma | It becomes a normal Project; sync seeds a fresh "Inbox" Project on next tick. |

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
