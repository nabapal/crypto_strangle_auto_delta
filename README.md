# Delta Strangle Enterprise Platform

Modernized control plane for the BTC/ETH short strangle automation. The stack now consists of:

- **Backend** – FastAPI + async SQLAlchemy microservice exposing configuration, trading control, and analytics APIs.
- **Frontend** – React + Ant Design admin UI for configuration, control, and analytics.
- **CLI** – `production_delta_trader.py` for quick bootstrapping and health checks.

## Directory Layout

```
backend/   # FastAPI application, database models, trading engine
frontend/  # React admin dashboard built with Vite
```

## Quickstart

### One-command local run

```bash
./scripts/start_local.sh
```

The script clears previous SQLite artifacts, points `DATABASE_URL` at the shared `data/` directory (handy for future container volume mounts), activates the Python virtualenv, and runs both the FastAPI backend (`http://localhost:8001`) and the React dev server (`http://localhost:5173`). Hit <kbd>Ctrl+C</kbd> to stop both services.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --port 8001 --reload
```

### Frontend

```bash
cd frontend
cp .env.example .env  # adjust VITE_API_BASE_URL for your backend host
pnpm install
pnpm dev
```

Set `VITE_API_BASE_URL` to the FastAPI base URL that includes the `/api` prefix (the sample `.env.example` points to `http://localhost:8001/api`). In production deployments where the UI is served from a different domain, update the value accordingly so all React Query calls target the live backend.

The SQLite file now lives under `data/delta_trader.db`; this folder can be bind-mounted when containerizing the stack so the host retains trading history.

### API Debug Logging

Flip on verbose HTTP tracing when you need to inspect every call between the dashboard and backend:

- Set `DEBUG_HTTP_LOGGING=true` in `.env` (or export it) to enable request/response logging within FastAPI. Logs will appear in the backend terminal with payloads truncated to 4 KB.
- Set `VITE_ENABLE_API_DEBUG=true` in `frontend/.env` to mirror the same diagnostics in the browser console via Axios interceptors.
- Set `DELTA_DEBUG_VERBOSE=true` to trace every outbound Delta Exchange API call (method, path, status, latency). When enabled the backend also logs truncated request/response payloads with sensitive fields masked.

Turn the flags back to `false` once you're done to avoid noisy logs in production.

## Documentation

- [Live Control Telemetry & UX Enhancement Plan](docs/live-control-enhancement-plan.md)
- [Backend ↔ Delta Exchange Debugging Plan](docs/backend-delta-debug-plan.md)

### CLI Helpers

```bash
python production_delta_trader.py runserver
python production_delta_trader.py check
```

## Testing

```bash
cd backend
pytest
```
