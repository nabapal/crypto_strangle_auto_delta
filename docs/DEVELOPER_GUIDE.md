## Option Trading Fee Calculation (Delta Exchange)

### Overview
Delta Exchange charges a taker/maker fee of 0.015% of the notional size for options trades (Monsoon Offer, 50% OFF), with a fee capping feature: the fee is capped at 5% of the premium paid/received. The lower of these two values is charged as the trading fee for both buying and selling options.

### Formula
- **Notional Size**: `underlying_price * contract_size * quantity`
- **Notional Fee**: `notional_size * 0.00015`
- **Premium Value**: `contract_size * quantity * premium`
- **Premium Cap**: `premium_value * 0.05`
- **Fee Charged**: `min(notional_fee, premium_cap)`

### API Usage
To quote the fee for an option trade, use:

```http
POST /api/trading/fees/quote
Content-Type: application/json

{
  "underlying_price": 26200,
  "contract_size": 0.001,
  "quantity": 300,
  "premium": 15,
  "order_type": "taker"
}
```

Response:
```json
{
  "notional": 7860.0,
  "notional_fee": 1.179,
  "premium_value": 4.5,
  "premium_cap": 0.225,
  "applied_fee": 0.225,
  "cap_applied": true,
  "order_type": "taker",
  "breakdown": {
    "notional_fee": 2.358,
    "premium_cap": 0.45,
    "applied_fee": 0.45,
    "cap_applied": true
  }
}
```

### Example Calculation
Trader buys 300 contracts of BTC OTM option at $15 premium, underlying at $26,200:
- Notional: `26200 * 0.001 * 300 = $7860`
- Notional Fee: `0.015% * $7860 = $1.179`
- Premium Value: `0.001 * 300 * $15 = $4.5`
- Premium Cap: `5% * $4.5 = $0.225`
- **Fee Charged**: `$0.225` (since premium cap < notional fee)

If the premium cap is higher than the notional fee, the notional fee is charged instead.
# Delta Strangle Enterprise Platform – Developer Guide

## Project Overview
Delta Strangle Enterprise Platform automates a short-strangle trading strategy on Delta Exchange. The system combines a FastAPI backend, a React + Vite administrator dashboard, and operational scripts to manage configuration, session lifecycle, analytics, and structured logging. The platform enables operators to monitor live sessions, tweak strategy parameters, ingest rich telemetry, and deploy to production with minimal friction.

---

## Architecture Summary

### High-Level Components
- **Backend (`backend/`)**: FastAPI application with async SQLAlchemy ORM, service layer orchestration, authentication, analytics, and log ingestion.
- **Frontend (`frontend/`)**: React + TypeScript single-page application built with Vite, using Ant Design, React Router, and React Query to deliver dashboards and controls.
- **Scripts & Ops (`scripts/`, root)**: Shell/Python utilities for starting local stacks, deploying production bundles, and running trading/webhook diagnostics.
- **Persistence (`data/`, `logs/`)**: SQLite database for trading metadata, analytics, and ingested logs; JSON log files for backend/frontend.
- **Containerization (`docker/`, `docker-compose.prod.yml`)**: Dockerfiles and Compose stack for production deployments.

### Folder Structure at a Glance
```
backend/
  app/
    api/              # FastAPI routers (auth, trading, analytics, logs, configs)
    core/             # Settings, database session, security primitives
    middleware/       # Request/response logging middleware
    models/           # SQLAlchemy ORM models (users, configs, sessions, logs)
    schemas/          # Pydantic models for request/response bodies
    services/         # Trading engine facade, analytics, log tailer, auth, config
    main.py           # FastAPI application factory, startup/shutdown hooks
  tests/              # pytest suite for API and service validation
frontend/
  src/
    api/              # Axios clients & React Query hooks
    components/       # Shared UI widgets (ProtectedRoute, tables, charts)
    context/          # Auth and configuration contexts
    pages/            # Views: Dashboard, Logs, Configuration, Login
    hooks/utils/      # Custom React hooks and helpers
  vite.config.ts      # Vite build configuration
scripts/
  start_local.sh      # One-command local stack runner
  deploy_prod.sh      # Production deployment helper (Docker Compose)
  migrate_add_option_price_ranges.sh  # Safe SQLite migration for price-based strike columns
  analyze_leg_prices.py  # Inspect CE/PE fills from session CSV + backend logs
  test_webhook_l1.py  # Websocket tester for Delta option prices
  sell_delta_option.py, etc.
Docker & Ops files
  docker/
  docker-compose.prod.yml
  production_delta_trader.py
```

### Runtime Data Flow
1. Operators sign in via the frontend, receiving JWTs from the FastAPI auth endpoints.
2. React components call `/api/**` routes with bearer tokens.
3. Backend services persist configurations, sessions, analytics snapshots, and log entries in SQLite (or an alternate DB via `DATABASE_URL`).
4. `TradingService` orchestrates the `TradingEngine`, capturing runtime telemetry and lifecycles.
5. `BackendLogTailService` tails `logs/backend.log`, deduplicates, and writes entries into the database for UI retrieval.
6. Frontend dashboards poll runtime endpoints, fetch analytics snapshots, and render log streams with filtering.

---

## Core Logic & Workflows

### Authentication
- **Routes**: `/api/auth/register`, `/api/auth/login`, `/api/auth/me`.
- **Flow**: `AuthService.create_user` hashes passwords, enforces unique emails; `authenticate` verifies credentials and issues JWTs via `create_access_token`. Dependencies (`get_current_active_user`) protect trading/config routes.

### Configuration Management
- **Service**: `ConfigService` handles CRUD and activation of `TradingConfiguration` records.
- **Activation**: Only one configuration can be active. `activate_configuration` toggles `is_active` flags atomically.
- **API**: `/api/configurations` endpoints reflect these operations, returning Pydantic responses defined in `schemas/config.py`.
- **Strike selection**: Config payloads expose `strike_selection_mode` (`delta` or `price`). Price mode requires `call_option_price_min/max` and `put_option_price_min/max`, constraining the acceptable option premiums for each leg. Validation rules live in `TradingConfigPayload` to enforce non-null guardrails, ordering, and positive values.

### Trading Lifecycle
- **Control Endpoint**: `POST /api/trading/control` accepts actions (`start`, `stop`, `restart`, `panic`) through `TradingControlRequest`.
- **Orchestration** (`TradingService.control`):
  1. Load configuration from DB.
  2. For `start`/`restart`, create `StrategySession`, snapshot config, import any open Delta Exchange positions into the session, then dispatch `TradingEngine.start`.
  3. For `stop`, call `TradingEngine.stop` and mark session halted.
  4. For `panic`, invoke `TradingEngine.panic_close`, stopping session if a strategy was active.
  5. Commit changes and produce structured log events (using `logging_context`).
- **Runtime Snapshot**: `TradingService.runtime_snapshot` merges live engine state, persisted metadata, and ensures defaults for totals/limits.
- **Heartbeat**: `/api/trading/heartbeat` surfaces engine status and active configuration ID when available.

### Session Auditing
- **Listing**: `/api/trading/sessions` returns `StrategySessionSummary`, including derived duration, exit reason, and leg summaries extracted from metadata.
- **Detail**: `/api/trading/sessions/{id}` joins `OrderLedger` and `PositionLedger`, returning full lifecycle data, config snapshot, and analytics metadata.

### Analytics Aggregation
- **Service**: `AnalyticsService` computes KPIs and chart data.
- `latest_snapshot` returns cached `TradeAnalyticsSnapshot` entries; if missing, aggregates total realized/unrealized PnL on the fly.
- `record_session_snapshot` normalizes metadata (totals, trailing metrics, PnL history) and stores snapshot upon session stop.

### Logging & Telemetry
- **Backend Ingest**: `BackendLogTailService` listens for filesystem events, dedupes using `line_hash`, persists to `BackendLogEntry`.
- **Retention**: `BackendLogRetentionService` prunes entries older than `BACKEND_LOG_RETENTION_DAYS`.
- **Frontend/Telemetry**: `/api/logs/frontend` endpoints accept optional client log batches (`FrontendLogEntry`); `VITE_ENABLE_REMOTE_LOGS` toggles usage.
- **UI**: Log Viewer page filters by level, event, correlation ID, and expands structured payloads.
- **Strike selection metadata**: `TradingEngine` emits `selection_metadata` structures capturing spot reference, chosen contracts, and distance percentages; they surface in runtime summaries, session exports, and backend logs for auditability.

### Frontend Workflows
- **Auth Context**: Maintains token, exposes `login`, `logout`, `refresh` logic.
- **Protected Routes**: `ProtectedRoute` ensures only authenticated users reach dashboard pages.
- **React Query Hooks**: Under `src/api` & `src/hooks`, encapsulating API calls (config list, runtime, analytics, logs) with caching/polling.
- **UI Components**: Ant Design forms/tables display configuration panels, PnL charts, log tables, session history, and analytics tiles.
- **Advanced Analytics Layout**: `AnalyticsDashboard` now renders metrics in grouped rows (`Performance Summary`, `Activity Snapshot`, `Per-Trade Averages`, `Win Metrics`, `Risk Extremes`). The first group highlights net PnL with historical timestamp context, and each group pulls formatter logic from the shared helpers in `AnalyticsDashboard.tsx`. When adding new metrics, extend the appropriate `MetricGroup` so cards inherit responsive grid behavior.
- **Theme & Time Utilities**: `ThemeProvider` (in `src/context/ThemeContext.tsx`) centralizes Ant Design theming and supports the header light/dark toggle, while `TimeDisplay` renders synchronized UTC/IST timestamps for operators; both are covered by Vitest suites in `src/components/__tests__/ThemeToggle.test.tsx` and `src/components/__tests__/TimeDisplay.test.tsx`.

---

## Use Cases & Features

| Feature | Technical Flow |
| --- | --- |
| User onboarding | `POST /api/auth/register` → `POST /api/auth/login` → store JWT → `GET /api/auth/me`. |
| Config management | CRUD via `/api/configurations`; activation flips `is_active`. Frontend uses AntD forms. |
| Strategy control | Dashboard triggers `/api/trading/control` with actions. `TradingEngine` orchestrates start/stop/panic. |
| Cleanup stale sessions | `POST /api/trading/sessions/cleanup` marks all lingering `running` sessions as stopped without placing trades. |
| Live monitoring | `/api/trading/runtime` & `/api/trading/heartbeat` feed React Query hooks for status tiles and control panel. |
| Session history | `/api/trading/sessions` & `/api/trading/sessions/{id}` provide chronological data (orders, positions, metadata). |
| Analytics dashboards | `AnalyticsService.latest_snapshot` supplies KPIs/charts to frontend analytics pages. |
| Log viewer | `/api/logs/backend` & `/api/logs/frontend` with pagination/filtering; ingestion via tail service and optional UI batching. |
| Production deployment | `docker-compose.prod.yml` + `deploy_prod.sh` orchestrate build, nginx static serving, and backend service. |

---

## API / Function / Class Reference (Highlights)

### Authentication (`app/api/auth.py`)
- `register_user(payload: UserCreate) -> UserRead`
  - Creates a new user, hashing the password and enforcing uniqueness. 201 Created.
- `login_user(form_data: OAuth2PasswordRequestForm) -> AuthResponse`
  - Verifies credentials, issues JWT via `create_access_token`, returns token + user payload.
- `read_current_user(current_user: User) -> UserRead`
  - Returns the authenticated user, leveraging dependency injection (`get_current_active_user`).

### Trading (`app/api/trading.py` & `TradingService`)
- `control_trading(payload: TradingControlRequest) -> TradingControlResponse`
  - Dispatches `start/stop/restart/panic`; interacts with `TradingEngine`, persists session state.
- `trading_heartbeat() -> dict`
  - Returns engine status (idle/running), optionally active configuration id.
- `trading_runtime() -> StrategyRuntimeResponse`
  - Merges live engine snapshot and latest session metadata.
- `list_sessions() -> list[StrategySessionSummary]`
  - Lists sessions with derived duration, exit reason, leg summaries.
- `get_session_detail(session_id: int) -> StrategySessionDetail`
  - Returns full session data, orders, positions, metadata.

Key `TradingService` methods:
- `control(command)` – orchestrates engine operations and logging.
- `heartbeat()` – merges engine status + latest session metadata.
- `runtime_snapshot()` – ensures a consistent response even when engine idle.
- `get_sessions()` – fetches all `StrategySession` records.
- `_create_session(config)` – persists new session with config snapshot & metadata.
- `_mark_session_stopped()` – finalizes session state, captures analytics.

### Analytics (`app/services/analytics_service.py`)
- `latest_snapshot() -> AnalyticsResponse`
  - Returns cached snapshot or computes totals, normalizes chart data.
- `record_session_snapshot(session) -> TradeAnalyticsSnapshot`
  - Normalizes metadata, persists aggregated KPIs and chart data.

### Config (`app/services/config_service.py`)
- `list_configurations()` → all configs.
- `get_active_configuration()` → active configuration (if any).
- `create_configuration(payload)` → inserts new config.
- `update_configuration(config_id, payload)` → updates fields.
- Supports `StrikeSelectionMode` transitions with automatic normalization of percentage inputs (`normalize_percentage`) and persists price-mode distances on the ORM model.
- `activate_configuration(config_id)` → make active, deactivate others.
- `delete_configuration(config_id)` → removes inactive config.

### Auth Service (`app/services/auth_service.py`)
- `create_user(payload)` → persists new user, hashed password.
- `authenticate(payload)` → verify credentials, return `AuthResponse` or raise HTTP errors.
- `ensure_initial_superuser(email, password)` → bootstrap admin on startup.
- `get_user_by_email`, `get_user_by_id` helpers.

### Models (selected)
- `TradingConfiguration` – strategy parameters, trailing rules, active flag, timestamps.
- `StrategySession` – tracks session lifecycles, config snapshot, metadata, relationships to orders/positions.
- `OrderLedger` / `PositionLedger` – audit logs of orders and positions per session.
- `TradeAnalyticsSnapshot` – stores aggregated KPIs and chart data.
- `BackendLogEntry` / `FrontendLogEntry` – structured log storage with metadata fields.

Refer to `app/schemas/` for exact request/response shapes (Pydantic models such as `TradingControlRequest`, `StrategyRuntimeResponse`, `AnalyticsResponse`, `BackendLogQuery`).

---

## Configuration & Setup

### Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp ../.env.example backend/.env  # copy relevant section and populate secrets
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```
Environment variables (see `app/core/config.py`):
- `DATABASE_URL` (default `sqlite+aiosqlite:///../data/delta_trader.db`)
- `JWT_SECRET_KEY`, `JWT_EXPIRES_MINUTES`
- `INITIAL_SUPERUSER_EMAIL`, `INITIAL_SUPERUSER_PASSWORD`
- `BACKEND_LOG_INGEST_ENABLED`, `BACKEND_LOG_PATH`
- `ALLOWED_ORIGINS`, `API_PREFIX`, `LOG_LEVEL`, `DEBUG_HTTP_LOGGING`

> **Upgrading existing databases**: If you are upgrading from a build prior to Nov 2025, run `scripts/migrate_add_option_price_ranges.sh data/delta_trader.db` (adjust the path for remote hosts) to backfill the price-mode columns before starting services. The helper scripts (`start_local.sh`, `deploy_prod.sh`) invoke this migration automatically when they detect a local SQLite file.

### Frontend Setup
```bash
cd frontend
pnpm install
cp ../.env.example frontend/.env
pnpm dev -- --host 0.0.0.0 --port 5173
```
Environment variables:
- `VITE_API_BASE_URL` (e.g., `http://localhost:8001/api`)
- `VITE_LOG_ENDPOINT`, `VITE_LOG_API_KEY`, `VITE_ENABLE_REMOTE_LOGS`
- `VITE_ENABLE_API_DEBUG`, `VITE_APP_VERSION`, dedup settings.

### One-Command Local Run
Ensure root virtualenv `.venv` exists with backend package installed:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e backend[dev]
```
Then run:
```bash
./scripts/start_local.sh
```
This script:
1. Cleans stale SQLite DBs & ensures `data/` and `logs/` directories.
2. Sources root `.venv`.
3. Runs `scripts/migrate_add_option_price_ranges.sh` when a local DB exists to backfill strike-selection columns (safe backup included).
4. Launches Uvicorn backend → logs to `logs/backend.log`.
5. Ensures pnpm dependencies, starts Vite dev server → logs to `logs/frontend.log`.
6. Exposes backend on `http://localhost:8001`, frontend on `http://localhost:5173` (or next free port).

### Production Deployment
1. Copy and configure environment: `cp .env.prod.example .env.prod`.
2. Review Dockerfiles (`docker/backend.Dockerfile`, `docker/frontend.Dockerfile`) and nginx config.
3. Deploy with `./scripts/deploy_prod.sh` (builds, restarts Compose). The script now runs `migrate_add_option_price_ranges.sh` automatically when an on-host SQLite file is detected, ensuring price-mode columns exist before containers start.
4. Monitor via `docker compose -f docker-compose.prod.yml logs -f backend` and verify log viewer.

---

## Dependencies & Integrations

### Python Backend
- **FastAPI** (`fastapi`, `uvicorn[standard]`) for API and ASGI serving.
- **SQLAlchemy[asyncio]**, **aiosqlite** for ORM and async database access.
- **Pydantic v2**, **pydantic-settings** for validation and configuration.
- **httpx[http2]**, **websockets** for external API/WebSocket integrations.
- **passlib[bcrypt]**, **python-jose[cryptography]**, **email-validator**, **python-multipart** for authentication and form handling.
- **python-json-logger**, **watchdog** for structured logging and filesystem tailing.

### Frontend
- **React 18**, **React DOM**, **React Router DOM** for SPA structure.
- **@tanstack/react-query** for data fetching/cache.
- **Ant Design**, **@ant-design/icons** for UI components.
- **axios**, **dayjs**, **recharts** for HTTP requests, date handling, and charts.
- Build tooling: **pnpm**, **Vite**, **TypeScript**, ESLint + Prettier.

### External Integration Points
- `TradingEngine` (not detailed here) connects to Delta Exchange REST/WebSocket APIs using credentials from environment variables (`DELTA_API_KEY`, etc.).
- Log ingestion optionally consumes remote telemetry from the frontend when `VITE_ENABLE_REMOTE_LOGS` is true.

---

## Development Guide

### Backend Contributions
- Use async functions (`AsyncSession`) for DB access.
- Define schemas in `app/schemas` before exposing new endpoints.
- Encapsulate business logic inside `app/services` to keep routers thin.
- Leverage `logging_context` for correlation IDs.
- Add pytest coverage in `backend/tests`; use httpx `ASGITransport` for integration-like tests.
- Run `pytest` and ensure log ingestion services handle new events gracefully.

### Frontend Contributions
- Add API calls under `src/api` or `src/hooks`; wrap network calls with React Query.
- Keep authentication logic within `AuthContext`; use `ProtectedRoute` for gated views.
- Prefer Ant Design components (Forms, Tables, Layout) for consistency.
- Run `pnpm run lint` and `pnpm run build` before committing.

### Coding Standards & Tips
- Maintain structured logging (JSON) for backend events.
- Keep bundle sizes manageable—consider `manualChunks` if new pages grow large.
- Document new environment variables in `.env.example` and README.
- When touching frontend visuals, extend the CSS variable palette in `src/styles.css` and ensure light/dark contrast stays WCAG-compliant. The analytics dashboard leverages `--chart-line-gross`, `--chart-line-fees`, and grouped card classes (`.analytics-group-card`, `.analytics-summary-item`) to keep layouts consistent across themes.
- When altering DB models, ensure `Base.metadata.create_all` still succeeds or introduce migrations.

---

## Known Issues & TODOs
- **Start Script Dependency**: `scripts/start_local.sh` uses root `.venv`; ensure backend package installed there (`pip install -e backend[dev]`).
- **Bundle Size Warning**: Vite emits chunk-size warnings (>500 kB). Investigate code-splitting or adjust `build.chunkSizeWarningLimit` if needed.
- **Timezone-aware Datetimes**: Replace `datetime.utcnow()` usage with `datetime.now(datetime.UTC)` to silence deprecation warnings in tests and services.

---

## Enhancements Overview

Detailed plans for the upcoming feature work (history ordering, dark-mode chart contrast, analytics export, and CI/CD automation) now live in `docs/enhancements.md`. Consult that document for phased milestones, validation criteria, and environment notes.

Highlights:
- **History Tab Ordering** – newest entries first with regression coverage.
- **Dark Mode Chart Contrast** – theme tokens for axis labels and tooltips.
- **Analytics Export** – CSV-first endpoint plus optional Excel support.
- **CI/CD Pipeline** – local hooks, GitHub Actions workflow, and deployment guardrails.

Refer to the enhancements document when creating tickets or coordinating releases; update both files if scope evolves.

---

## Examples & Diagrams

### Sample API Usage
Authenticate and fetch runtime snapshot:
```bash
curl -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=secret"
# → {"access_token": "...", "token_type": "bearer", ...}

curl http://localhost:8001/api/trading/runtime \
  -H "Authorization: Bearer <token>"
```

Trigger a strategy start:
```bash
curl -X POST http://localhost:8001/api/trading/control \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "start", "configuration_id": 1}'
```

Query backend logs (latest 50 errors):
```bash
curl "http://localhost:8001/api/logs/backend?level=ERROR&limit=50" \
  -H "Authorization: Bearer <token>"
```

### Textual Sequence Diagram (start action)
1. **Frontend** → `/api/trading/control` (`start`, config_id=1)
2. **Auth Dependency** validates JWT → allows request.
3. **TradingService.control** loads configuration, creates new `StrategySession`, snapshots config.
4. `TradingEngine.start` invoked (async background execution).
5. Session committed; response returns `{status: "starting", strategy_id: ...}`.
6. Logs emitted: `session_created`, `strategy_start` events.

### Sequence (Log ingestion)
1. Backend writes JSON log line to `logs/backend.log`.
2. `BackendLogTailService` detects file append via watchdog.
3. Line hashed → inserted into `BackendLogEntry` if new.
4. Frontend Log Viewer queries `/api/logs/backend` for recent entries.

---

## Quick Reference Commands
```bash
# Run backend tests
cd backend
pytest

# Lint & build frontend
cd frontend
pnpm run lint
pnpm run build

# Local stack
./scripts/start_local.sh

# Production deploy
./scripts/deploy_prod.sh
```

---

## Summary
This guide captures the platform’s architecture, data flow, core workflows, APIs, setup, and operational guidance. Use it to onboard new engineers, plan feature work, or audit integrations. Keep it updated as the trading engine evolves, new services emerge, or infrastructure shifts.
