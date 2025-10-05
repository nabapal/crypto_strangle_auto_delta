# Backend ↔ Delta Exchange Debugging Plan

## Goals
- Capture every outbound call the backend makes to Delta Exchange, including request metadata, payloads, signatures, and responses.
- Correlate backend trading workflow events (entry retries, trailing triggers) with the exact Delta API calls that occurred.
- Provide operators with reusable scripts and logging configuration to reproduce and inspect issues in staging or production.

## Observability Enhancements

### 1. Structured Logging Middleware
- **HTTP Layer**: Extend existing request/response middleware to tag logs with correlation IDs and request origin (frontend vs internal worker).
- **Trading Workflow**: Add log statements at key lifecycle stages in `TradingService` and `TradingEngine`:
  - Session creation, entry scheduling, each retry attempt, trailing SL activation, forced exit.
  - Include strategy ID, configuration ID, attempt counters, and timing metrics.
- **Order/Position Persistence**: Log SQLAlchemy flush outcomes with inserted IDs to match later API responses.

### 2. Delta Exchange Client Instrumentation
- Wrap `DeltaExchangeClient.request` with:
  - Unique call ID (UUID) logged before and after the HTTP call.
  - Request method, path, params/body (with sensitive fields masked), latency, HTTP status.
  - Raw response snapshot truncated to configurable size (default 2 KB) to avoid massive logs.
- Capture signature payload and timestamp to debug auth errors (with secret omitted).
- On errors, log exception type plus response body for fast triage.

### 3. Correlation IDs & Context Propagation
- Generate a `trace_id` per strategy session start; inject into:
  - Trading control response payload.
  - Logger context (using `contextvars` + custom formatter).
  - Delta client headers (`X-Trace-ID`) to trace through external observability tools if supported.
- Persist `trace_id` in `StrategySession.session_metadata` to link DB entries back to log streams.

### 4. Runtime Telemetry Endpoint
- Extend planned `/api/trading/runtime` to include recent Delta call history:
  ```json
  {
    "delta_calls": [
      {
        "id": "baf8…",
        "method": "POST",
        "path": "/v2/orders",
        "status": 201,
        "latency_ms": 245,
        "timestamp": "2025-10-04T18:20:31Z"
      }
    ]
  }
  ```
- Expose last N entries (configurable, default 10) to the frontend for quick inspection without leaving the UI.

### 5. External Tooling
- Provide ready-to-run scripts:
  - `scripts/delta_probe.py` to replay a single request with current credentials, verifying signatures and inspecting responses.
  - `scripts/analyze_logs.py` to filter structured logs for a particular `trace_id` or strategy.
- Recommend enabling HTTPX built-in logging (`httpx` logger at DEBUG) during deep dives.

## Logging Configuration

### Logging Format
- Switch to JSON logs via `uvicorn` settings (`--log-config`) or `structlog` for structured output:
  ```json
  {
    "timestamp": "2025-10-04T18:20:31.123Z",
    "level": "INFO",
    "logger": "delta.client",
    "trace_id": "abc123",
    "event": "delta_request",
    "method": "POST",
    "path": "/v2/orders",
    "latency_ms": 245,
    "status_code": 201
  }
  ```

### Environments
- **Local/Dev**: Enable verbose logging by default; integrate with existing `DEBUG_HTTP_LOGGING` flag.
- **Prod**: Gate sensitive payload logging behind `DELTA_DEBUG_VERBOSE=true`; default to headers + metadata only.
- **Test**: Use `caplog` to assert critical log entries in unit tests (e.g., verifying retries).

## Debug Workflow Checklist
1. Enable `DEBUG_HTTP_LOGGING=true` and `DELTA_DEBUG_VERBOSE=true` in `.env`.
2. Restart backend via `scripts/start_local.sh` (ensures new log config is loaded).
3. Trigger trading control actions or run targeted probes.
4. Tail logs with jq for readability:
   ```bash
   uvicorn ... | jq -c 'select(.trace_id=="abc123")'
   ```
5. Use `scripts/analyze_logs.py --trace abc123` to aggregate the timeline.
6. If Delta rejects signatures, replay with `scripts/delta_probe.py` to isolate differences in canonical payload.

## Future Enhancements
- Integrate OpenTelemetry traces for end-to-end spans (frontend → backend → Delta) with exporters to Jaeger/Tempo.
- Ship log bundles to object storage automatically when severe errors occur.
- Implement rate-limit detectors to notify when Delta throttles requests.
