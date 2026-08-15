# token-dashboard

Self-hosted dashboard for [Hermes](https://github.com/cori/hermes-agent) token-usage analytics. Reads `token_calls.db` (written by `hermes-token-analysis`'s `token_capture.record_call()`), renders an HTML dashboard, serves it via HTTP.

## Architecture

```
┌─────────────────────────────────────┐
│  Host                                │
│  ~/.hermes/token_calls.db            │ ← Hermes writes here in-process
│            │                         │
│            ▼                         │
│  bind-mount → /data/token_calls.db   │ (Runtipi volume)
└────────────┬─────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  token-dashboard container           │
│                                      │
│  Regenerator thread (every 5min):    │
│    reads /data/token_calls.db        │
│    writes /data/index.html           │
│                                      │
│  HTTP server (port 8000):            │
│    /         → serves index.html     │
│    /health   → JSON status           │
└─────────────────────────────────────┘
```

No host cron needed. No copy steps. One source of truth for rendering.

## Local dev

```bash
pip install -e ".[dev]"
pytest -v
```

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` | Where the DB lives and where `index.html` is written |
| `PORT` | `8000` | HTTP port to bind |
| `REFRESH_INTERVAL` | `300` | Seconds between regenerations |

## Deployment

This repo's `main` branch builds and pushes an image to `ghcr.io/cori/token-dashboard:sha-<short>`. The Runtipi entry lives at [`cori/rtappstore/apps/token-dashboard/`](https://github.com/cori/rtappstore/tree/main/apps/token-dashboard).

## Data flow (what's NOT in this repo)

- `token_calls.db` lives on the host (`~/.hermes/token_calls.db`), bind-mounted into the container.
- The image never sees API keys, billing data, or the DB file itself in the repo.
- The picker-watch JSONL log (`~/.hermes/cache/model-picker-watch.jsonl`) is read by the dashboard's picker-watch panel — also bind-mounted.

## Tests

```bash
pytest -v
```

The test suite covers:

- Regenerator writes valid HTML for a fixture DB
- Output contains the summary cards, breakdown table, and picker-watch panel
- Regenerator is deterministic across runs
- HTTP server serves `/`, `/health`, writes index.html on startup

## License

Private. Not for redistribution.