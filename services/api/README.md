# irma-api

Async FastAPI backend for the Irma desktop assistant.

```bash
uv sync
cp .env.example .env       # fill secrets
uv run irma-api          # serves on 127.0.0.1:8765 by default

# Or:
uv run python -m irma_api
```

Endpoints:

| Method | Path | Phase |
| --- | --- | --- |
| `GET /api/v1/signals` | recent observer signals | 2 |
| `POST /api/v1/refresh` | force re-observation | 2 |
| `GET /api/v1/state` | current AgentState | 2 |
| `GET /api/v1/stream` | SSE stream of AgentState transitions | 3 |
| `GET /api/v1/standup` | Claude-synthesized `StandupBrief` | 3 |

Strict checks: `uv run ruff check .`, `uv run mypy --strict src/irma_api`,
`uv run pytest`.

## Apple Reminders sync

Mirrors each `Project` in Irma into its own macOS Reminders list named
**`Irma · <ProjectName>`**, with Tasks as flat reminders inside. The Inbox
project lives in **`Irma · Inbox`**, which is also where phone-captured
quick-adds land. Changes in either place flow back on the next sync
(≤60 s, or instantly via `POST /integrations/reminders/sync`).

In your Reminders sidebar you'll see something like:

    Irma · Inbox
    Irma · Video Model
    Irma · MIT Deep Learning
    ...one entry per active Irma project

Renaming `Irma · X` on the phone to `Irma · Y` renames Project X to Y in
Irma. Renaming it to drop the `Irma · ` prefix unlinks the project (Irma
forgets the calendar; it stays on your phone untouched). Archiving a
project in Irma deletes its phone list.

### One-time setup

1. Build the helper (macOS only):

       ./tools/reminders-helper/build.sh

   The output binary is checked in at
   `tools/reminders-helper/bin/irma-reminders-helper`; rebuild after editing
   anything under `tools/reminders-helper/Sources`.

2. Start the API as usual. On first link, macOS will prompt for
   Reminders permission against the helper binary.

3. Link:

       curl -X POST http://127.0.0.1:8765/api/v1/integrations/reminders/link

   On success, returns `{"linked": true}` and the Inbox list + lists for
   every active project appear in Reminders.

### Useful commands

| Action | Command |
| --- | --- |
| Force a sync now | `curl -X POST http://127.0.0.1:8765/api/v1/integrations/reminders/sync` |
| Unlink (preserve lists on phone) | `curl -X DELETE http://127.0.0.1:8765/api/v1/integrations/reminders/link` |
| Reset macOS TCC grant | `tccutil reset Reminders com.irma.reminders-helper` |
| Opt-in end-to-end test | `IRMA_REMINDERS_E2E=1 uv run pytest tests/integrations/test_reminders_e2e.py` |
