# Live Control Telemetry & UX Enhancement Plan

## Objectives
- Expose granular, real-time trading telemetry so operators can verify schedule, execution method, and safety controls without leaving the dashboard.
- Provide a richer Live Control tab that narrates the full lifecycle (pre-entry, entry, live management, exit) for each strategy run.
- Maintain API-first design so the frontend consumes structured data that can later power alerting or external dashboards.

## Current State Snapshot
- **APIs**: `/api/trading/control`, `/api/trading/heartbeat`, `/api/trading/sessions` return high-level status plus stored orders/positions after the fact.
- **Trading engine**: Records orders and positions but treats fills as single-shot limit orders and stores minimal runtime metadata.
- **UI**: Live Control tab shows active config, strategy status, and a few KPIs but lacks forward-looking schedule info and per-leg analytics.

## Feature Backlog & Phasing

### Phase 1 – Backend Instrumentation
- Track scheduled entry time, selected contracts (symbol, expiry, delta), and entry attempts in `StrategyRuntimeState`.
- Implement limit-order retry logic with market fallback; write order method + retry count into `OrderLedger`.
- Persist richer `session_metadata` (config id, scheduled entry, entry method, attempts, selected contracts).
- Add trailing stop metadata (activation flag, level, timestamp) to runtime state.

### Phase 2 – Live Metrics & Persistence
- Poll Delta tickers for active leg symbols to compute mark price, PnL absolute/percent.
- Update `PositionLedger.analytics` with `{"mark_price", "pnl_abs", "pnl_pct"}` on each monitoring cycle.
- Maintain overall strategy metrics: aggregated PnL, trailing status, time-to-exit.

### Phase 3 – Runtime API Contract
- Introduce `GET /api/trading/runtime` (or extend `/heartbeat`) returning a consolidated payload:
  - `status` (`waiting`, `entering`, `live`, `cooldown`).
  - `scheduled_entry_at`, `time_to_entry`, `entry` block (method, attempts, timestamp, per-leg contracts).
  - `positions` array with entry time, sell price, current price, PnL absolute/%, trailing info.
  - `strategy` summary with overall PnL, exit time, time-to-exit, config metadata.
- Update Pydantic schemas and tests to cover the new structure.

### Phase 4 – Frontend UX Upgrade
- Revamp Live Control tab into four panels:
  1. **Schedule & Status** – config name, underlying, target delta range, scheduled entry, countdown timers.
  2. **Entry Execution** – attempts, order method (limit → market fallback), per-leg contract details.
  3. **Position Health** – per-leg cards showing entry vs. current price, PnL %, trailing SL status, last level change.
  4. **Exit Timeline** – planned exit time, remaining duration, trailing/exit triggers, manual exit controls.
- Poll the new runtime endpoint (with React Query) and surface warning states when retries escalate or trailing activates.

### Phase 5 – Polishing & Observability
- Flash notifications for entry success/failure, trailing activation, forced exit.
- Optional: persist event log entries for audit (e.g., `strategy_events` table) and expose via UI.
- Add unit/integration tests for retry logic, trailing updates, and API shape.

## Data Model Adjustments
- Add optional columns:
  - `OrderLedger.order_type` (`limit`/`market`), `retry_count`.
  - `PositionLedger.mark_price`, `pnl_pct` (if denormalizing improves queries).
- Ensure JSON payloads (`session_metadata`, analytics) stay ISO-8601 and numeric only for easy frontend parsing.

## Test & Rollout Plan
1. Extend backend test suite with fixtures covering retry fallback, trailing activation, and runtime payload serialization.
2. Provide a mocked runtime response for frontend development to decouple UI until backend endpoint is ready.
3. Deploy backend changes first; feature-flag the new endpoint.
4. Ship frontend UI with graceful degradation (fallback to existing stats if runtime payload absent).

## Open Questions / Next Decisions
- Should retries & order method be configurable per config? (Likely yes—consider `max_retry`, `retry_delay` fields.)
- Do we want to persist historic runtime snapshots for analytics, or only expose the latest state?
- How should we alert operators of critical states (web push, email, slack)? – Future enhancement.

## Next Actions
- [ ] Finalize and sign off on the runtime API schema.
- [ ] Start Phase 1 backend instrumentation (estimate: ~1.5 days including tests).
- [ ] Deliver mock runtime payload + frontend wireframe for review before implementing UI changes.
