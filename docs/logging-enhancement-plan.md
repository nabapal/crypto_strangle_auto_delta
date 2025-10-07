# Logging Enhancement Plan

## Objectives
- Emit structured JSON logs across backend services and the frontend client for consistent ingestion.
- Capture every critical decision, market data input, order lifecycle event, and error with enough context to reproduce issues.
- Correlate events across services via shared identifiers and stream logs to an Elastic Stack (Elasticsearch, Logstash, Kibana) deployment for analysis and alerting.

## Status Snapshot (October 7 2025)
- ✅ **Phase 1 – Backend Foundations**: Structured logging, correlation IDs, task monitoring, and dependency instrumentation are live and covered by tests.
- ✅ **Phase 2 – Frontend Telemetry**: Unified logger shipped, UI flows instrumented, `/api/logs` ingest endpoint online, and remote batching enabled with API-key protection.
- ✅ **Phase 3 – Aggregation & Operations**: Dockerised ELK stack, Filebeat shipper, retention/alerting guidance, and an operational runbook are available in `infra/logging/`.

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

## Phase 3 – Aggregation & Operations (Completed)

### Centralised sink assets
- `infra/logging/docker-compose.yml` spins up Elasticsearch 8.15, Kibana, and Logstash with single-node defaults.
- `infra/logging/logstash/pipeline/logstash.conf` ingests Beats traffic on port 5044, normalises fields, and indexes documents into `delta-logs-*` indices.
- `infra/logging/filebeat.yml` tails `logs/backend.log` and `logs/frontend.log` as newline-delimited JSON and forwards them to Logstash.

To launch the stack locally:
```bash
cd infra/logging
docker compose up -d
# Start Filebeat in a separate shell
filebeat -e -c filebeat.yml
```

### Retention & alerting
- Default Kibana data views: `delta-logs-*` with runtime fields for `strategy_id`, `session_id`, and `event`.
- Hot retention: 30 days in the primary index; configure ILM in Kibana → Stack Management → Index Lifecycle to roll to cold storage at 180 days.
- Recommended Kibana alert rules:
  - **Delta API Failure Surge**: threshold on `event:delta_request_failed` with 5+ hits in 1 minute.
  - **Strategy Error Exits**: `event:strategy_exit` & `status:error` to warn operations.
  - **Frontend Error Boundary**: `event:ui_error_boundary_triggered` to notify incident response.
  - **Websocket Heartbeat Gap**: absence of `websocket_quote_heartbeat` for 3 minutes.

### Validation & rollout checklist
1. Deploy backend and frontend with `LOG_LEVEL=INFO`, `LOG_INGEST_API_KEY`, and `VITE_LOG_API_KEY` configured.
2. Run a simulated session; verify correlation IDs link API, engine, and UI events in Kibana Discover.
3. Confirm Filebeat shipping via Logstash by checking Kibana dashboard panels for PnL timelines and websocket uptime.
4. Enable the alert rules above and test notification channels.

---

## Operational Runbook
1. **Trace a correlation ID**: Search `correlation_id:"<value>"` across `delta-logs-*` to follow a user journey from the browser through FastAPI and the trading engine.
2. **Toggle log levels**: Update the `LOG_LEVEL` environment variable on the backend deployment and recycle the process. For frontend verbosity, adjust `VITE_ENABLE_API_DEBUG` and rebuild.
3. **Purge noisy telemetry**: Tune `VITE_LOG_DEDUP_WINDOW` / `VITE_LOG_DEDUP_THRESHOLD` or backend sampling intervals to reduce chatter before re-running Filebeat.
4. **Respond to persistent frontend errors**: Filter for `event:ui_error_boundary_triggered`, inspect `data.component_stack`, follow the matching correlation ID into backend logs, and create a Jira incident if reproducible.
5. **Monitor ingestion health**: Kibana → Stack Monitoring for Elasticsearch/Logstash stats; Filebeat logs for shipper back-pressure; backend `/api/logs/batch` HTTP 4xx spikes require frontend key rotation.

---

## Next Steps
- Automate ILM and alert provisioning via Terraform or Kibana saved objects.
- Explore shipping database-stored `frontend_logs` via periodic export or Logstash JDBC input.
- Introduce Role-Based Access Control for `/api/logs` using FastAPI dependencies when multi-tenant dashboards are required.
