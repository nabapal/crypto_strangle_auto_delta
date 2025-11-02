Enhancements Roadmap
This document tracks the next set of improvements for the Delta Strangle Enterprise Platform, focused on usability and streamlined deployment.

1. Display Strike Distance on Live Control ✅ (shipped Oct 12, 2025)
Show how far the selected CE and PE strikes are from spot when entries occur.
- Live Control → Entry Execution → Selected Contracts now appends “±X.XX% from spot” next to each delta value, using live spot with backend fallbacks.
- Live Control → Position Health cards surface the same label immediately after the Unrealized PnL value for every leg.
- Frontend derives the percentage from contract strikes or symbol-encoded strikes; backend strike data remains optional.
- Manual smoke test: verified distinct percentages for CE/PE during entry and in active positions with BTC spot ~114,778.
2. History Tab Paging ✅ (shipped Oct 12, 2025)
Add pagination controls to the history tab (frontend: TradeHistoryTable).
- Backend `/api/trading/sessions` now accepts `page` and `page_size` parameters and responds with a paginated payload including totals and page count.
- UI renders Ant Design pagination with page/size pickers (10/25/50/100), keeps previous data visible while new pages load, and clamps to the last available page when deletions shrink history.
- React Query now requests `page`,`page_size` and uses `keepPreviousData` placeholder to avoid flashing.
- Tests cover newest-first ordering plus dedicated pagination coverage (page size boundaries, disjoint result sets).
3. CSV Export in History Tab ✅ (shipped Oct 13, 2025)
Add a CSV export control to the trade history tab with backend streaming support.
- Backend `/api/trading/sessions/export?format=csv` streams one row per strategy, including spot entry/exit, CE/PE metadata, strike deltas, and distance-from-spot percentages with blanks when data is missing.
- Frontend button triggers the download, logs success/failure, and surfaces Ant Design toasts while preventing repeat clicks during export.
- pytest coverage asserts column ordering, CE/PE fallback population, and CSV byte content; manual smoke test compares export to a reference session from staging.
4. Simple CI/CD Workflow
Development:
Developers push feature/fix branches to GitHub (never directly to main).
Preprod:
Preprod host fetches the new branch, builds, and tests manually (no automated pipeline required).
If tests and manual QA pass, preprod merges the branch into main (or master).
Production:
Production host pulls the latest main branch and redeploys.
Notes:
No automated GitHub Actions or deployment scripts required for now.
Document manual test steps and merge criteria in the developer guide.
Tag releases after production deploys for traceability.

5. Live Control Risk Visualization
Deliver a live payoff dashboard that reflects the core delta-strangle strategy configuration and runtime limits inside the Live Control tab.
- Backend: expose a `/trading/risk-snapshot` endpoint built from current positions, configured strikes, contract sizes, trailing stop settings, max profit/loss thresholds, and latest spot data. Generate a payoff ladder at discrete spot intervals using actual leg entry prices/PnL rules (no Black–Scholes greeks). Include markers for trailing SL, max loss, max profit, and breakeven lines.
- Data model: persist the computed snapshot with runtime metadata so historical sessions and local replays can reuse the visualization without recomputation.
- Frontend: embed a responsive chart (Recharts/ECharts) that plots payoff vs spot, overlays trailing SL and limit bands, highlights live spot, and displays projected net PnL, realized/unrealized components, and distance-to-threshold annotations.
- Interaction: allow toggling between “Current Ladder” (using live mark prices) and “Session Entry Ladder” (using entry prices), and provide hover tooltips summarizing leg-wise contribution, active limits, and time since last update.
- Validation: add backend unit tests to verify payoff ladder calculations against known scenarios, plus UI story/tests to ensure the chart renders with mock snapshots and handles empty or partial data gracefully.

6. Advanced Analytics Session Rollups ✅ (shipped Oct 13, 2025)
Analytics dashboard KPIs, streaks, and charts now operate on per-strategy session totals rather than individual legs.
- Backend session rollups aggregate net/gross PnL, fees, win/loss flags, streaks, and drawdown for each strategy before emitting history metrics and chart points.
- Frontend updates rename dashboard labels (e.g., session count, per-session averages, session histogram) and adjust tooltips to match the new aggregation level.
- Updated pytest coverage verifies the session-level rollups and chart counts match the new semantics.
7. Strike Selection Price Mode ✅ (shipped Nov 2, 2025)
Enable operators to pick contracts using a price-distance strategy instead of delta targeting.
- Added `strike_selection_mode` to trading configurations with validation for required distance percentages.
- Trading engine normalizes tickers to identify spot references, selects contracts at configured percentage offsets, and logs selection metadata.
- Frontend configuration panel exposes a toggle for delta vs price mode, validates inputs, and mirrors persisted values from the API.
- Session exports and runtime summaries now include `ce_distance_pct`/`pe_distance_pct` sourced from price mode offsets.