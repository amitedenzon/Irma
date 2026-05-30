# Chat Backend Parity + Read/Write Tools — Design

**Date:** 2026-05-28
**Goal:** Make the chat tab expose two backends ("Local" and "Claude") with identical abilities: read/write Google Calendar, read/write Projects + Tasks, and send email (to self).

## Problem

The chat tab today exposes three backends:

| Label  | Backend      | Tool use? |
| ------ | ------------ | --------- |
| Local  | `ollama`     | yes       |
| API    | `anthropic`  | yes       |
| Claude | `claude_cli` | **no** — shells out to `claude -p --disallowedTools "*"` |

Tools available: `read_calendar` (readonly) and `send_email` (recipient locked to operator). No write path to Calendar, no Project/Task access from chat.

The user wants the chat to drive calendar (read + write), projects/tasks (read + write), and email. Backends visible in the UI must all have the same set of abilities; anything that can't, hide.

`claude_cli` cannot host these tools without standing up an MCP server — out of scope for this slice. It is redundant with `anthropic` (same provider, different transport), so it is the one to hide.

## Decision

1. **Hide `claude_cli`** from the chat UI by filtering it out of `/chat/backends`.
2. **Relabel `anthropic` → "Claude"** in the frontend.
3. **Add six new tools** to the existing `ToolRegistry` so both remaining backends pick them up via the existing tool-call loop in `routers/chat.py`.
4. **Bump the Google OAuth scope** from `calendar.readonly` to `calendar.events` so writes work. User re-runs `irma-api auth google` once.
5. **Append one line to the persona prompt** listing the tools so the model reaches for them.

## Out of scope

- MCP server for `claude_cli`. Hidden, not adapted.
- `update_*` / `delete_*` tools for projects and tasks. Add later if needed.
- Email recipient parameter — `send_email` stays self-only (server-set `to`).
- Streaming tool calls to the UI.

## Backend visibility

### `/chat/backends` filter

`routers/chat.py::get_backends` returns every registered backend today. Add a hardcoded hide-list:

```python
_HIDDEN_BACKENDS: Final[frozenset[str]] = frozenset({"claude_cli"})
```

The handler filters both `available` and `models`, and if the resolved default is in the hide-list, falls back to the first non-hidden backend (or `None`).

`POST /chat` itself does **not** enforce the hide-list — it still accepts `claude_cli` for callers that pass it explicitly (e.g. scripts/tests). The filter is a UI-surface concern only.

### Frontend label change

`apps/desktop/src/main/chat/ChatView.tsx::BACKEND_LABEL`:

```ts
const BACKEND_LABEL: Record<string, string> = {
  ollama: "Local",
  anthropic: "Claude",
};
```

`claude_cli` entry removed (it will never appear in `available`).

## New tools

All new tools live in `services/api/src/irma_api/tools/` and conform to the existing `Tool` protocol (`tools/base.py`). All return a plain-text string suitable for feeding back to the model.

### `create_calendar_event`

Lives in `tools/calendar.py` next to `ReadCalendarTool`.

- **Args:** `summary: str` (required), `start: str` (RFC3339), `end: str` (RFC3339), `description: str` (optional), `location: str` (optional).
- **Behavior:** POST to Google Calendar `events.insert` on `primary` calendar. Uses the same `Aiogoogle` + retry path as `ReadCalendarTool`. Returns `"created event <htmlLink>"`.
- **Errors:** `calendar_unlinked`, `calendar_auth_failed`, `calendar_http_error`, `invalid_args` (start/end not parseable, end ≤ start).

### `list_projects`

Lives in `tools/projects.py` (new file).

- **Args:** `status: list[str]` (optional, defaults to `["active"]`). Validated against `ProjectStatus`.
- **Behavior:** `ProjectRepo.list(statuses=...)`. Returns a numbered list, one project per line: `<id> <name> [status] (target: <date>)`.
- **Errors:** `invalid_args` for unknown status values.

### `create_project`

Same file.

- **Args:** `name: str` (required), `calendar_keywords: list[str]` (optional), `target_date: str` (optional ISO date), `priority: int` (optional), `goals: list[str]` (optional).
- **Behavior:** `ProjectRepo.create(ProjectCreate(...))`. Returns `"created project <id> <name>"`.
- **Errors:** `conflict` on duplicate name, `invalid_args` on schema violations.

### `list_tasks`

Lives in `tools/tasks.py` (new file).

- **Args:** `project_id: str` (optional), `status: list[str]` (optional), `due_before: str` (optional ISO date), `scheduled_from: str` (optional ISO date), `scheduled_to: str` (optional ISO date). All map directly to the filters exposed by `TaskRepo.list`.
- **Behavior:** `TaskRepo.list(...)`. Returns one task per line: `<id> [status] <title> (project: <project_id>, due: <date>, scheduled: <date>)`.
- **Errors:** `invalid_args`.

### `create_task`

Same file.

- **Args:** `project_id: str` (required), `title: str` (required), `status: str` (optional, defaults to `"todo"`), `due_date: str` (optional ISO), `scheduled_for: str` (optional ISO), `estimated_minutes: int` (optional).
- **Behavior:** `TaskRepo.create(TaskCreate(...))`. Returns `"created task <id> <title>"`.
- **Errors:** `not_found` if `project_id` is unknown, `invalid_args` on schema violations.

### `complete_task`

Same file.

- **Args:** `task_id: str` (required).
- **Behavior:** `TaskRepo.update(task_id, TaskUpdate(status=TaskStatus.DONE))` — same path the `POST /tasks/{id}/complete` endpoint uses. Idempotent (re-completing returns the existing row with `completed_at` already set). Returns `"completed task <id> <title>"`.
- **Errors:** `not_found`.

## OAuth scope bump

`auth/google_oauth.py::SCOPES` changes from:

```python
SCOPES = ("https://www.googleapis.com/auth/calendar.readonly",)
```

to:

```python
SCOPES = ("https://www.googleapis.com/auth/calendar.events",)
```

`calendar.events` is strictly broader than `calendar.readonly` (it allows reading + writing events on calendars the app creates or the user shares), so both `ReadCalendarTool` and `TimeAgent` continue to work after re-auth. The two existing readers' `_build_creds()` scope strings are updated to match.

User must re-run `irma-api auth google` once — the existing refresh token is scoped narrower and will 403 on writes. Add a one-line note to the `calendar_auth_failed` `ToolError.detail` reminding them.

## Persona prompt

Append one line to `_SYSTEM_PROMPT` in `routers/chat.py` (the inline prompt — `prompts/irma_persona.md` is for `LeadAgent`, separate path):

```
Available tools: read_calendar, create_calendar_event, list_projects, create_project, list_tasks, create_task, complete_task, send_email. Use them when the user's request needs them; don't narrate the call.
```

## Tool registration

`app.py` lifespan currently registers `ResendSendTool` and `ReadCalendarTool` conditionally on env presence. Extend the same pattern:

- Calendar write tool — gated on `google_oauth_refresh_token` (same as read).
- Project + Task tools (five of them) — always registered; they need the `SignalStore` connection, which is unconditional.

Each project/task tool takes `store: SignalStore` in `__init__` and instantiates its repo inside `call()` (matching the per-request pattern in `routers/projects.py`).

`app.py` logs at startup already include `tools=registry.names()`, so new tools surface in the log line without changes.

## Files touched

| File | Change |
| ---- | ------ |
| `services/api/src/irma_api/tools/calendar.py` | Add `CreateCalendarEventTool`; update scope string in `_build_creds`. |
| `services/api/src/irma_api/tools/projects.py` | New file: `ListProjectsTool`, `CreateProjectTool`. |
| `services/api/src/irma_api/tools/tasks.py` | New file: `ListTasksTool`, `CreateTaskTool`, `CompleteTaskTool`. |
| `services/api/src/irma_api/auth/google_oauth.py` | Bump `SCOPES`. |
| `services/api/src/irma_api/agents/time_agent.py` | Match `_build_creds` scope to new value. |
| `services/api/src/irma_api/app.py` | Register the six new tools. |
| `services/api/src/irma_api/routers/chat.py` | `_HIDDEN_BACKENDS` filter on `get_backends`; appended tool list line in `_SYSTEM_PROMPT`. |
| `apps/desktop/src/main/chat/ChatView.tsx` | Remove `claude_cli` from `BACKEND_LABEL`; rename `anthropic` → "Claude". |

## Testing

- **Unit:** one happy-path + one error-path test per new tool, mocking the repo / `Aiogoogle` layer. Pattern matches existing `tests/tools/test_calendar.py` / `test_resend.py`.
- **Backends filter:** test `/chat/backends` no longer surfaces `claude_cli` even when the binary is on PATH (use a fake `llm_registry` in `app.state`).
- **End-to-end:** add a script under `scripts/` (matching `email_today_calendar.py`) that round-trips chat → `create_task` → `list_tasks` against a real local API. Manual run only.

## Risks

- **OAuth re-auth.** The user must re-run `irma-api auth google` after deploy or every calendar call 403s. Mitigated by the error message in `calendar_auth_failed.detail`.
- **Tool-call latency on Local.** Ollama's tool support is reliable on recent llama.cpp builds but adds ~1 round trip per tool. Acceptable; chat already shows a "thinking…" affordance.
- **Prompt injection via calendar events.** Existing risk (a malicious event description could try to coerce a tool call). `send_email` is recipient-locked; `create_calendar_event` would let injected content schedule a meeting, but only on the user's own calendar — bounded blast radius. Worth a follow-up review if we ever broaden recipients.
