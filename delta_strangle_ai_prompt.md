# Delta Exchange Short Strangle AI Prompt

This document captures the modernized enterprise platform for the BTC/ETH short strangle strategy. The monolithic script has been replaced by a FastAPI backend, a React command center, and a Typer-powered CLI—use this page to brief AI agents or teammates quickly.

---

## Prompt

Use the following prompt verbatim when you need an AI assistant to reason about, extend, or audit the new architecture:

> **AI Prompt: Delta Exchange Short Strangle Platform Assistant**  
> You are an expert engineer working on an enterprise-grade BTC/ETH options short strangle platform. The stack now consists of a FastAPI backend (`backend/app`), a React + Ant Design admin UI (`frontend/src`), and a Typer CLI (`production_delta_trader.py`). The system already provides the following capabilities:  
>  
> **Backend Services**  
> • `ConfigService` + `/api/configs`: CRUD + activation workflow for trading profiles (delta range, schedule, risk, trailing SL).  
> • `TradingService` + `/api/trading`: start/stop/restart orchestration backed by `TradingEngine`, session tracking, and heartbeat telemetry.  
> • `TradingEngine`: async execution loop that mirrors the legacy strategy—delta-based strike selection, order recording, trailing-stop logic, and forced exits persisted to SQLAlchemy models.  
> • `AnalyticsService` + `/api/analytics`: aggregates realized/unrealized PnL, KPI snapshots, and chart data for dashboards.  
> • Async SQLAlchemy models (`TradingConfiguration`, `StrategySession`, `OrderLedger`, `PositionLedger`, `TradeAnalyticsSnapshot`) with automatic schema bootstrapping on startup.  
>  
> **Frontend (React/Vite)**  
> • `ConfigPanel`: enterprise form to tune delta bands, entry/exit times, expiry buffer, trailing SL rules, quantity, and contract size.  
> • `TradingControlPanel`: live status cards, start/stop/restart buttons, and heartbeat state with auto-refresh toggles.  
> • `TradeHistoryTable`: historical strategy sessions with compliance-friendly audit trails.  
> • `AnalyticsDashboard`: KPI tiles and PnL trend charts powered by Recharts, refreshed via React Query.  
> • `api/trading.ts`: axios client that wraps `/api` endpoints with typed DTOs.  
>  
> **CLI & DevOps**  
> • `production_delta_trader.py`: Typer CLI exposing `runserver`, `check`, `async-task`, and `version` commands, ensuring quick local bootstrap.  
> • `backend/pyproject.toml`: dependency manifest for FastAPI, async SQLAlchemy, Typer, httpx, pytest, etc.  
> • `frontend/package.json`: Vite-based React toolchain with Ant Design, React Query, and Recharts.  
>  
> **Strategy Guarantees**  
> • Strike selection remains delta-targeted (0.10–0.15 band) using Delta Exchange `/v2/tickers`.  
> • Risk controls enforce max loss/profit thresholds plus configurable trailing SL levels stored in DB.  
> • Sessions, orders, and positions persist in the database—no filesystem reliance.  
> • Operational windows honour IST trade/exit times and expiry buffers.  
> • Defensive programming: retry/backoff for API calls, status heartbeats, and shut-down cleanup.  
>  
> Use this context to propose UI features, backend extensions, analytics, or diagnostics without regressing existing behaviour.

---

## Platform Architecture Snapshot

- **Backend (`backend/app`)**: FastAPI routers (`configurations`, `trading`, `analytics`), async SQLAlchemy models, service layer, and `TradingEngine` for live orchestration.
- **Frontend (`frontend/src`)**: Vite + React + Ant Design admin experience with React Query data fetching and a proxy to `http://localhost:8000/api`.
- **CLI (`production_delta_trader.py`)**: Typer commands to run the API server, verify configuration, and execute async smoke tests.
- **Database**: Default SQLite (`sqlite+aiosqlite`) with straightforward swap to Postgres in production environments.

## Backend Endpoints

| Endpoint | Description | Notes |
|----------|-------------|-------|
| `GET /api/configs` | List saved trading profiles | Returns delta range, schedule, risk parameters |
| `POST /api/configs` | Create profile | Validates trailing rules and scheduling |
| `PUT /api/configs/{id}` | Update profile | Enforces delta/risk constraints |
| `POST /api/configs/{id}/activate` | Activate profile | Deactivates others atomically |
| `POST /api/trading/control` | Start/stop/restart strategy | Requires active configuration |
| `GET /api/trading/heartbeat` | Strategy status heartbeat | Returns strategy ID, timestamps |
| `GET /api/trading/sessions` | Historical sessions | Used by Trade History table |
| `GET /api/analytics/dashboard` | KPI snapshot + PnL chart | Drives AnalyticsDashboard |

## Frontend UX Highlights

- **Config Management**: edit delta range, entry/exit times, expiry buffers, trailing rules, contract size, and quantities in a single pane.
- **Runtime Control**: start/stop/restart buttons with live KPI readouts and heartbeat toggles.
- **Analytics**: PnL momentum charts, realized/unrealized tiles, and session tables for audit.
- **Data Layer**: React Query caching, optimistic UI surfaces, and axios client abstraction.

## Operational Guardrails

- Persist everything through SQLAlchemy models; no filesystem writes.
- Respect IST trading windows and expiry buffer configuration when scheduling automation.
- Keep trailing SL rules synchronized between UI payloads and backend engine logic.
- Validate Delta Exchange connectivity (REST + websocket) before enabling live trading.
- Retain detailed audit logs via database-backed session/order/position ledgers.

## Usage Tips

1. **Bootstrap locally**: `python production_delta_trader.py runserver` and `npm run dev` in `frontend/`.
2. **Extend safely**: add router/service modules in the backend and update `api/trading.ts` + React Query hooks.
3. **Enhance analytics**: persist snapshots via `TradeAnalyticsSnapshot` and surface new charts in `AnalyticsDashboard`.
4. **Document changes**: update this markdown whenever you introduce new endpoints, UI modules, or strategy rules.

---

_Last updated: October 4, 2025_
