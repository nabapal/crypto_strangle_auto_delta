# Logging Enhancement Plan

## Objectives
- Emit structured JSON logs across backend services and the frontend client for consistent ingestion.
- Capture every critical decision, market data input, order lifecycle event, and error with enough context to reproduce issues.
- Correlate events across services via shared identifiers and surface them through an in-repo SQLite-backed log viewer for analysis and troubleshooting without external dependencies.

## Status Snapshot (October 7 2025)
- ✅ **Phase 1 – Backend Foundations**: Structured logging, correlation IDs, task monitoring, and dependency instrumentation are live and covered by tests.
- ✅ **Phase 2 – Frontend Telemetry**: Unified logger shipped, UI flows instrumented, `/api/logs` ingest endpoint online, and remote batching enabled with API-key protection.
- ✅ **Phase 3 – Aggregation & Operations**: Backend log tailing, SQLite persistence, retention cleanup, and the React log viewer deliver self-contained observability.

---

## Phase 1 – Backend Foundations (Completed)

### Structured logging baseline
- `backend/app/services/logging_utils.py` configures a `StructuredJsonFormatter`, context propagation via `ContextVar`, and request correlation support.
- `backend/app/main.py` bootstraps logging once, enforces JSON output, and respects the `LOG_LEVEL` setting.
- `backend/app/middleware/request_logging.py` now issues correlation IDs, injects HTTP metadata, and mirrors IDs back to clients.

### Trading engine instrumentation
- `backend/app/services/trading_engine.py` logs loop iterations, exit rules, trailing state transitions, and order lifecycles with sampled debug output via `LogSampler`.
- Background tasks are wrapped with `monitor_task` to surface latent failures.

### External dependencies
- `backend/app/services/delta_exchange_client.py` captures request/response metrics, rate-limit headers, and authentication state.
- `backend/app/services/delta_websocket_client.py` emits connection, subscription, heartbeat, and sampled quote events.
- `backend/app/core/database.py` warns on slow queries and pool exhaustion using SQLAlchemy events.

### Error handling & controls
- Log sampling rates (`ENGINE_DEBUG_SAMPLE_RATE`, `TICK_LOG_SAMPLE_RATE`) are tunable from configuration.
- `tests/test_logging_controls.py` validates sampling, middleware correlation, and task monitoring behaviour.

---

## Phase 2 – Frontend Telemetry (Completed)

### Unified logger & interceptors
- `frontend/src/utils/logger.ts` centralises batching, rate limiting, correlation tracking, and remote forwarding (secured by `VITE_LOG_API_KEY`).
- `frontend/src/api/client.ts` applies Axios interceptors that log request/response metadata and propagate correlation IDs from HTTP headers.

### Component & hook instrumentation
- `TradingControlPanel`, `AnalyticsDashboard`, `TradeHistoryTable`, and `ConfigPanel` emit structured events for user actions, auto-refresh cycles, query cache hits/misses, and mutation outcomes.
- `frontend/src/hooks/useDeltaSpotPrice.ts` reports websocket connectivity, retries, and parse errors via the unified logger.
- `frontend/src/components/ErrorBoundary.tsx` captures React render failures and forwards them to the telemetry pipeline.

### Frontend log ingestion
- `/api/logs/batch` (`backend/app/api/logs.py`) accepts authenticated log batches, persists them in the `frontend_logs` table, and mirrors entries to server-side structured logs.
- Settings: `LOG_INGEST_API_KEY` (required header `X-Log-API-Key`) and `LOG_INGEST_MAX_BATCH` cap inbound traffic; the frontend supplies its key via `VITE_LOG_API_KEY`.
- `frontend/src/env.d.ts` reflects all log-related environment variables for TypeScript safety.
- New pytest coverage (`tests/test_log_ingest.py`) verifies authentication, persistence, and batch limits.

---

docker compose up -d
## Phase 3 – Aggregation & Operations (Completed)

### Backend ingestion & storage
- `backend/app/services/log_tail_service.py` tails `logs/backend.log`, parses newline-delimited JSON, and persists entries into the new `backend_logs` table with de-duplication via content hashes.
- `backend/app/services/log_retention_service.py` runs as a background task, pruning `backend_logs` rows older than `BACKEND_LOG_RETENTION_DAYS` (defaults to 7) on an hourly cadence.
- `backend/app/api/logs.py` exposes `/api/logs/backend` with pagination, free-text search, and filters for level, event, logger, correlation ID, and time ranges.
- Settings: `BACKEND_LOG_INGEST_ENABLED`, `BACKEND_LOG_PATH`, `BACKEND_LOG_POLL_INTERVAL`, `BACKEND_LOG_BATCH_SIZE`, and `BACKEND_LOG_RETENTION_DAYS` govern the service behaviour.

### Frontend log viewer
- `frontend/src/components/LogViewer.tsx` renders the backend log stream in Ant Design tables with column filters, search inputs, and an optional auto-refresh toggle.
- Query integration uses React Query for cache consistency and exponential backoff; expanding a row reveals the full JSON payload stored alongside each entry.
- The viewer ships as a dedicated "Log Viewer" tab within the dashboard, allowing operators to pivot from configuration screens directly into correlated log trails.

### Validation & rollout checklist
1. Launch the app with `./scripts/start_local.sh`; confirm backend startup logs begin streaming into the Log Viewer without manual intervention.
2. Trigger a few control-plane actions (start/panic/stop). Verify correlation IDs line up across frontend telemetry (`frontend_logs`) and backend events (`backend_logs`).
3. Toggle log levels and confirm ingestion continues; use the date range filter to isolate recent noise and ensure retention pruning clears out older rows after the configured window.
4. For headless deployments, run `pytest backend/tests/test_backend_log_api.py::test_backend_logs_endpoint_filters_and_pagination` to validate API filtering and pagination behaviour.

---

## Operational Runbook
1. **Trace a correlation ID**: Use the Log Viewer search (`Correlation ID` field) to follow a user journey end-to-end; expand matching rows to see the full payload.
2. **Toggle log levels**: Update the `LOG_LEVEL` environment variable on the backend deployment and recycle the process. For frontend verbosity, adjust `VITE_ENABLE_API_DEBUG` and rebuild.
3. **Purge noisy telemetry**: Tune `VITE_LOG_DEDUP_WINDOW` / `VITE_LOG_DEDUP_THRESHOLD` or backend sampling intervals to reduce chatter before exporting sessions for analysis.
4. **Respond to persistent frontend errors**: Filter for `event:ui_error_boundary_triggered`, inspect `data.component_stack`, follow the matching correlation ID into backend logs, and create a Jira incident if reproducible.
5. **Monitor ingestion health**: Keep an eye on the auto-refresh cycle in the Log Viewer and backend logs for `backend_log_tail` warnings. `/api/logs/backend` returning stale data typically signals file permissions or ingestion bottlenecks.

---

## Next Steps
- Add saved filter presets and CSV export inside the Log Viewer for rapid sharing during incident reviews.
- Introduce Role-Based Access Control for `/api/logs/backend` using FastAPI dependencies when multi-tenant dashboards are required.
- Extend ingestion to support optional archiving (e.g., nightly gzip exports) for long-term retention beyond the SQLite window.
