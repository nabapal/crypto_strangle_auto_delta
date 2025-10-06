# Logging Enhancement Plan

## Objectives
- Emit structured JSON logs across backend services and the frontend client for consistent ingestion.
- Capture every critical decision, market data input, order lifecycle event, and error with enough context to reproduce issues.
- Correlate events across services via shared identifiers and stream logs to an Elastic Stack (Elasticsearch, Logstash, Kibana) deployment for analysis and alerting.

## Phase 1 – Backend Foundations

### 1. Structured logging baseline
- Enable JSON formatting in `backend/app/main.py` (e.g., using `python-json-logger` or `structlog`) for consistent ingestion.
- Extend `RequestResponseLoggingMiddleware` to generate a `correlation_id` per request and stash it in a `contextvars.ContextVar` so downstream modules automatically include it.
- Add helper utilities (`backend/app/services/logging_utils.py`) to inject common context (strategy ID, session ID, configuration name, execution mode) into every log statement.

### 2. Trading engine instrumentation
- `_run_loop` / `_monitor_positions`: log cycle start/end, portfolio notional, latest PnL, trailing thresholds evaluated, decision outcomes, and latency.
- `_check_exit_conditions`: emit evaluation of each rule (max loss, max profit, trailing) with raw values and triggers.
- `_update_trailing_state`: log previous and new trailing levels, profit milestones, and rules responsible for changes.
- `_refresh_position_analytics`: capture quote freshness, symbol list, mark price sources (stream vs. REST fallback), and fallback warnings.
- `_place_live_order`, `_record_live_orders`, `_record_simulated_orders`, `_force_exit`, `_finalize_session_summary`: log order IDs, side, price, size, fills, retries, failure reasons, and exit rationale.

### 3. External dependencies
- `DeltaExchangeClient`: augment existing logs with instrument symbols, response body size (truncated), and latency buckets; log authentication status and rate-limit headers when present.
- `OptionPriceStream`: instrument connect/disconnect, subscription updates, heartbeat/liveness checks, message decode errors, and reconnection attempts.
- Database layer: use SQLAlchemy events to warn on slow queries and connection pool exhaustion.

### 4. Error handling & controls
- Wrap background tasks with `logger.exception` including context IDs to avoid silent failures.
- Make log level configurable via environment (e.g., `LOG_LEVEL=INFO`) and add sampling for noisy debug statements (e.g., every Nth market tick).
- Add unit tests (pytest + `caplog`) for critical flows to ensure required log entries remain.

## Phase 2 – Frontend Telemetry

### 1. Unified logger
- Introduce `src/utils/logger.ts` with leveled logging, environment-aware sinks (console in dev, remote ingestion in prod), and metadata injection (session ID, app version, user identifier).
- Replace ad-hoc `console.*` usage, including API debug options, with the unified logger.

### 2. Instrument application flows
- API client interceptors: log request/response timings, headers, payload summaries, and bubble correlation IDs from backend headers.
- Components:
  - `TradingControlPanel`: user actions (start/stop/panic), state transitions, trailing level updates, and error toasts.
  - `AnalyticsDashboard` / `TradeHistory`: data fetch successes/failures, cache hits/misses, chart update timing.
- Hooks: `useDeltaSpotPrice` to emit connection state, retry strategy, and stale data detection.
- Global error boundary: capture component stack traces and forward to logger + user notification.

### 3. Log forwarding
- Provide `/api/logs` endpoint (authenticated) to accept frontend log batches when third-party logging isnt available; store with `source=frontend` tag.
- Implement client-side rate limiting and deduplication to avoid bursts.

## Phase 3 – Aggregation & Operations

### 1. Centralized sink
- Deploy the Elastic Stack (ELK) on the free Basic license using the official Docker images (docker-compose bundle with Elasticsearch, Kibana, and optional Logstash).
- Configure Filebeat or Fluent Bit to ship JSON logs into Elasticsearch indices, retaining schema: `timestamp`, `level`, `service`, `source`, `strategy_id`, `session_id`, `correlation_id`, `event`, `payload`.

### 2. Retention & alerting
- Define retention policy (e.g., 30-day hot, 180-day cold archives).
- Alerting rules: surge in Delta API failures, repeated strategy exits with `error` reason, frontend error boundary triggers, heartbeat gaps from price stream.
- Dashboards/KPIs: order lifecycle timelines, trailing SL activations, API latency percentiles, websocket uptime.

### 3. Validation & rollout
- Document operational runbook explaining how to trace a correlation ID across services, toggle log levels, and query common issues.
- Stage rollout:
  1. Implement backend structured logging and correlation IDs.
  2. Instrument trading engine critical paths.
  3. Launch frontend logger and backend log ingestion endpoint.
  4. Integrate with aggregator, configure alerts/dashboards.
  5. Conduct verification run (simulated session) ensuring each checkpoint emits logs with proper context.

## Open Decisions
- Authentication/authorization model for `/api/logs` endpoint.
- Sampling thresholds for high-volume data.

## Next Steps
1. Implement Phase 1 foundation with JSON logging in place.
2. Deploy ELK Basic via Docker and configure log shippers.
3. Schedule telemetry rollout for frontend and align with security review for client log ingestion.
