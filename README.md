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

Environment variables are read from `backend/.env`. Use the consolidated `.env.example` in the repository root, copy the `# Backend` section into `backend/.env`, and fill in any secrets before launching.

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

Create `frontend/.env` by copying the `# Frontend` section from the root `.env.example`. Adjust `VITE_API_BASE_URL` so it points at the FastAPI host (include the `/api` suffix). When serving the UI from a different origin, update this value to target the production backend.

## API Debug Logging

Flip on verbose HTTP tracing when you need to inspect calls between the dashboard and backend:

- `DEBUG_HTTP_LOGGING=true` enables request/response logging within FastAPI (payloads truncated to 4 KB).
- `VITE_ENABLE_API_DEBUG=true` mirrors the diagnostics in the browser console via Axios interceptors.
- `DELTA_DEBUG_VERBOSE=true` traces all outbound Delta Exchange requests, logging masked payloads and latencies.

Remember to turn the flags back to `false` once troubleshooting is complete.

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
