# Analytics Export Runbook

This runbook describes how to monitor and troubleshoot the analytics history export feature exposed via `GET /api/analytics/export`.

## Overview
- **Purpose**: Streams CSV snapshots of analytics metrics, charts, and timelines for a requested date range.
- **Entry point**: `backend/app/services/analytics_service.py::AnalyticsService.export_history_csv` invoked by the FastAPI route `/api/analytics/export`.
- **Primary consumers**: Advanced Analytics dashboard export button and operator-driven scripts.

## Instrumentation
- Structured logs are emitted from the analytics service with enriched metadata.
  - **Success event**: `analytics_export_completed`
    - Fields: `duration_ms`, `timeline_records`, `format`, `strategy_id`, `preset`, `range_start`, `range_end`.
  - **Failure event**: `analytics_export_failed`
    - Fields: `duration_ms`, `format`, `strategy_id`, `preset`, `range_start`, `range_end` (raw request inputs).
- Logs flow into `logs/backend.log` and are ingested by the backend log viewer (`/logs` tab in the UI).
- Use the dashboard filter `event = analytics_export_completed` to monitor throughput and latency trends.

## Monitoring Checklist
1. **Latency**: Alert if `duration_ms` exceeds 5,000 ms for more than three exports within a 10-minute window.
2. **Failure rate**: Alert when `analytics_export_failed` appears more than once within 15 minutes.
3. **Record volume**: Track `timeline_records` to understand payload size and watch for sudden drops (may indicate missing data).
4. **Authentication errors**: HTTP 401/403 responses are surfaced via standard access logs—verify token validity before deeper debugging.

## Operational Playbook
1. **Identify impact**
   - Confirm affected strategy IDs or presets via log context.
   - Validate the frontend status by attempting an export in staging or via curl (using a valid JWT).
2. **Collect context**
   - Fetch the latest `analytics_export_completed` and `analytics_export_failed` events from the log viewer.
   - Capture the corresponding API request parameters (`start`, `end`, `preset`, `strategy_id`).
3. **Remediation steps**
   - **Data gaps**: Re-run analytics aggregation (`AnalyticsService.history`) or backfill timeline data.
   - **Performance issues**: Profile SQL queries, review recent deployments for schema changes, and consider limiting date ranges.
   - **Unhandled exceptions**: Inspect stack traces in `analytics_export_failed` logs, patch the offending code path, and re-deploy.
4. **Verification**
   - Trigger a manual export after fixes.
   - Ensure new `analytics_export_completed` events show healthy `duration_ms` and expected `timeline_records`.

## Escalation
- If latency or failures persist beyond 30 minutes after mitigation attempts, escalate to the platform reliability contact and attach relevant log excerpts and reproduction steps.
- Document remediation in the incident tracker and link to the log viewer query for future reference.
