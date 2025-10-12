Enhancements Roadmap
This document tracks the next set of improvements for the Delta Strangle Enterprise Platform, focused on usability and streamlined deployment.

1. Display Strike Distance on Live Control
Show how far the selected CE and PE strikes are from spot when entries occur.
- Live Control → Entry Execution → Selected Contracts: append “X% away from spot” next to each delta value.
- Live Control → Position Health cards: inject the percentage distance immediately after the Unrealized PnL value for each leg.
- Backend should expose the percentage distance if not already available; frontend renders it with two decimal precision.
- Update tests to cover the new field rendering (including edge cases when spot is missing).
2. History Tab Paging
Add pagination controls to the history tab (frontend: TradeHistoryTable).
Backend /api/trading/sessions should accept page and page_size query params and return paged results.
UI should show page numbers, next/prev, and total count. Default page size: 25 or 50.
Update tests to cover paging logic and edge cases (empty page, last page, etc).
3. CSV Export in History Tab
Add a CSV export button to the history tab.
Export one row per strategy session (strategy ID), including all session details (start/end time, config, PnL, fees, status, etc).
Backend endpoint /api/trading/sessions/export?format=csv streams the file; frontend triggers download and shows success/error.
CSV columns: strategy_id, activated_at, stopped_at, config_snapshot, total_pnl, total_fees, win_rate, trade_count, exit_reason, etc.
Update tests to verify CSV content and download flow.
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