# Delta Strangle Enterprise Platform

Modernized control plane for automated BTC/ETH short strangle trading. The platform spans a FastAPI backend, a React + Vite frontend, and CLI tooling for operational workflows.

## Platform Highlights

### Backend (FastAPI)

- Configuration CRUD with activation workflows and persistent strategy session metadata.
- Lifecycle commands (start/stop/restart/panic) coordinated by the shared trading engine.
- Analytics APIs producing KPI tiles, chart feeds, and trailing stop telemetry.
- Async SQLAlchemy data access with a SQLite default (swap the DSN for Postgres/MySQL in production).
- Feature-flagged logging controls for structured tracing of Delta Exchange interactions.
- Self-contained backend log ingestion service that tails `logs/backend.log`, stores entries in SQLite, and enforces retention windows.

### Frontend (React + Vite)

- Configuration forms covering delta ranges, schedules, trailing SL, and risk limits.
- Live control panel to monitor session status and trigger lifecycle commands.
- History views summarizing PnL, legs, orders, and trailing performance.
- Advanced analytics dashboards powered by Ant Design components and React Query.
- Optional client-side logging hooks for deep troubleshooting.
- Log Viewer tab for filtering backend events, searching correlation IDs, and expanding structured payloads without leaving the dashboard.

## Directory Layout

```
backend/   # FastAPI application, database models, trading engine
frontend/  # React admin dashboard built with Vite
scripts/   # CLI helpers and diagnostics
```

## Quickstart

### One-command local run

```bash
./scripts/start_local.sh
```

The helper script clears stale SQLite files, activates the backend virtualenv, and starts both services (`http://localhost:8001` for FastAPI and `http://localhost:5173` for the dashboard). Press <kbd>Ctrl+C</kbd> to stop everything.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --port 8001 --reload
```

Environment variables are read from `backend/.env`. Use the consolidated `.env.example` in the repository root, copy the `# Backend` section into `backend/.env`, and fill in any secrets before launching. Key toggles include log sampling (`ENGINE_DEBUG_SAMPLE_RATE`, `TICK_LOG_SAMPLE_RATE`), structured log ingestion controls (`BACKEND_LOG_INGEST_ENABLED`, `BACKEND_LOG_PATH`, `BACKEND_LOG_POLL_INTERVAL`, `BACKEND_LOG_BATCH_SIZE`, `BACKEND_LOG_RETENTION_DAYS`, `LOG_INGEST_MAX_BATCH`), and optional protection for the log batch endpoint via `LOG_INGEST_API_KEY`.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Create `frontend/.env` by copying the `# Frontend` section from the root `.env.example`. Adjust `VITE_API_BASE_URL` so it points at the FastAPI host (include the `/api` suffix). When serving the UI from a different origin, update this value to target the production backend. Remote telemetry is opt-in by default (`VITE_ENABLE_REMOTE_LOGS=false`); flip it to `true` only when you want the dashboard to post browser logs to the backend.

## Production Deployment

The repository ships with a self-contained production stack built on Docker Compose. It packages the FastAPI backend and the nginx-served React frontend while keeping logging, data, and automation on the host.

### 1. Prepare environment variables

Copy the template to `.env.prod` and fill in secrets:

```bash
cp .env.prod.example .env.prod
```

Key variables:

- `DATABASE_URL=sqlite+aiosqlite:////app/data/delta_trader.db`
- `BACKEND_LOG_INGEST_ENABLED=true` and `BACKEND_LOG_PATH=/app/logs/backend.log`
- `BACKEND_LOG_POLL_INTERVAL`, `BACKEND_LOG_BATCH_SIZE`, `BACKEND_LOG_RETENTION_DAYS`, `LOG_INGEST_MAX_BATCH`
- `ENGINE_DEBUG_SAMPLE_RATE`, `TICK_LOG_SAMPLE_RATE` for controlling engine telemetry verbosity
- `DELTA_API_KEY` / `DELTA_API_SECRET`
- `ALLOWED_ORIGINS` and `VITE_API_BASE_URL=https://your-domain/api`
- Optional `LOG_INGEST_API_KEY` to protect the `/api/logs/batch` endpoint

### 2. Review the compose stack

- `docker/backend.Dockerfile`: multi-stage Python image that installs dependencies into a virtualenv and exposes FastAPI on port 8001.
- `docker/frontend.Dockerfile`: builds the Vite app with pnpm and serves it via nginx using `docker/nginx.conf` to proxy `/api` to the backend.
- `docker-compose.prod.yml`: runs both services on the `app-net` bridge network, mounts `./data` → `/app/data` and `./logs` → `/app/logs`, and publishes port 80 (fronted by nginx).

### 3. Deploy with one command

```bash
./scripts/deploy_prod.sh
```

The script stashes local changes, syncs to `origin/master`, rebuilds images, restarts the compose stack, and prints reminders about verifying the log viewer. Run it whenever you need to refresh the production host.

### 4. Post-deploy checks

- Visit the dashboard (`https://your-domain/`) and open the **Log Viewer** tab to confirm backend ingestion is working.
- Tail container logs if needed:

  ```bash
  docker compose -f docker-compose.prod.yml logs -f backend
  ```

- Back up the `data/` directory regularly—it contains both trading metadata and persisted backend logs.

## API Debug Logging

Flip on verbose HTTP tracing when you need to inspect calls between the dashboard and backend:

- `DEBUG_HTTP_LOGGING=true` enables request/response logging within FastAPI (payloads truncated to 4 KB).
- `VITE_ENABLE_API_DEBUG=true` mirrors the diagnostics in the browser console via Axios interceptors.
- `DELTA_DEBUG_VERBOSE=true` traces all outbound Delta Exchange requests, logging masked payloads and latencies.

Remember to turn the flags back to `false` once troubleshooting is complete.

## Observability & Retention

- Backend logs are emitted in structured JSON, written both to stdout and `logs/backend.log`.
- `BackendLogTailService` streams new lines into the `backend_logs` table, making them queryable via the frontend Log Viewer and API (`/api/logs/backend`). Tune polling cadence (`BACKEND_LOG_POLL_INTERVAL`), batch size (`BACKEND_LOG_BATCH_SIZE`), and safety limits (`LOG_INGEST_MAX_BATCH`) to match your environment.
- `BackendLogRetentionService` purges entries older than `BACKEND_LOG_RETENTION_DAYS` (default 7 days).
- Use the Log Viewer tab to filter by level, correlation ID, event name, or free-text search; expand rows to inspect full payloads. Remote UI log ingestion remains disabled unless `VITE_ENABLE_REMOTE_LOGS=true`.
- Host-level rotation (`logrotate`, etc.) can be layered onto `logs/backend.log` without breaking ingestion—the tailer handles truncation and rotations automatically.

## Webhook / L1 Stream Tester

Use `scripts/test_webhook_l1.py` to monitor live best bid/ask data from Delta's websocket. The helper bootstraps the same `OptionPriceStream` used by the trading engine, making it easy to validate feeds outside the service loop.

```bash
python scripts/test_webhook_l1.py \
  --symbols C-BTC-95000-310125 P-BTC-95000-310125 \
  --duration 30 \
  --interval 0.5
```

- `--symbols` (required): option symbols to subscribe to.
- `--duration`: seconds to stream before exiting (`<=0` runs until interrupted).
- `--interval`: print frequency in seconds (default `1.0`).
- `--url`: override the websocket endpoint (useful for testnet or proxies).

## Documentation

- [Live Control Telemetry & UX Enhancement Plan](docs/live-control-enhancement-plan.md)
- [Backend ↔ Delta Exchange Debugging Plan](docs/backend-delta-debug-plan.md)

## CLI Helpers

```bash
python production_delta_trader.py runserver
python production_delta_trader.py check
```

## Testing

```bash
cd backend
pytest
```
