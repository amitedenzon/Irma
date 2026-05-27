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
