# Enhancements Roadmap

This document captures the upcoming improvements requested for the Delta Strangle Enterprise Platform, the phased execution strategy, and related operational considerations.

## Overview

Focus areas:

1. Reordering the analytics history tab so the newest entries appear first.
2. Fixing dark-mode visibility issues for analytics chart time labels.
3. Delivering downloadable analytics exports (CSV first, Excel optional).
4. Establishing automated checks and deployments across development, pre-production, and production environments.

Each phase below describes scope, implementation notes, success criteria, and follow-up tasks.

## Phase 0 – Discovery & Baseline

**Goals**
- Inventory current UI components: history tab, analytics chart, export capabilities.
- Capture baseline screenshots or Storybook entries for light/dark themes.
- Ensure tests exist for critical surfaces (unit, snapshot, or integration).

**Baseline Findings (Oct 11, 2025)**
- **History tab** renders via `frontend/src/components/TradeHistoryTable.tsx`, sourced from `/api/trading/sessions` (implemented in `backend/app/api/trading.py` & `TradingService.get_sessions`). Rows currently arrive unsorted from the database.
- **Analytics charts** live in `frontend/src/components/AnalyticsDashboard.tsx`, depending on `fetchAnalytics` and `fetchAnalyticsHistory`. Dark-mode styles draw from `frontend/src/styles.css` and Ant Design theme tokens.
- **Export surfaces** not yet implemented; analytics data aggregation handled by `backend/app/services/analytics_service.py` and exposed through `/api/analytics` + `/api/analytics/history`.
- **Reference imagery**: existing screenshots stored in `ui_snap/latest_ui.png` and `ui_snap/after_login.png`. Capture new light/dark history + analytics states before Phase 1 changes.
- **Tracking sheet**: create a shared checklist in project docs (e.g., `docs/qc/baseline_history.md`) to log future regressions. (TODO: add file once screenshots captured.)

**Success Criteria**
- List of affected files/components with owners.
- Documented baseline artifacts stored alongside QA references.
- Confirmed test coverage or backlog ticket to create it.

**Test Coverage Snapshot (Oct 11, 2025)**
- Backend integration tests already cover `/api/trading/sessions/{id}` (see `backend/tests/test_trading_api.py`) and analytics history aggregation (`backend/tests/test_analytics_history.py`).
- No dedicated backend test currently verifies `/api/trading/sessions` ordering; create a new test in `backend/tests/test_trading_api.py` during Phase 1.
- Frontend dashboard test (`frontend/src/pages/__tests__/Dashboard.test.tsx`) mocks history and analytics components—no direct assertions on ordering or chart theming; plan to add component-level tests (see TODOs below).
- No existing tests around CSV/Excel exports; QA strategy will rely on new endpoint tests once implemented.

**TODOs Raised**
- [x] Add backend test ensuring `/api/trading/sessions` returns newest session first (Phase 1).
- [x] Add Vitest/RTL coverage for `TradeHistoryTable` sorting and row rendering (Phase 1).
- [x] Add theme-aware coverage for `AnalyticsDashboard` dark-mode labels (Phase 2).
- [x] Define backend + frontend tests for analytics export endpoint/UI (Phase 3).

## Phase 1 – History Tab Ordering

**Implementation Notes**
- Prefer server-side ordering: update history query to sort by `timestamp DESC`.
- If API already sorted, reverse the array client-side before rendering.
- Propagate ordering logic through pagination or lazy-loading hooks.

**Status (Oct 11, 2025)**
- Backend `TradingService.get_sessions` now orders by `activated_at DESC NULLS LAST`, with an ID fallback to guarantee deterministic history results.
- Frontend `TradeHistoryTable` applies a defensive client-side sort so newest sessions render first even if cached data is stale.
- Regression coverage: `backend/tests/test_trading_api.py::test_list_sessions_returns_newest_first` and `frontend/src/components/__tests__/TradeHistoryTable.test.tsx`.

**Validation**
- Add backend test (or contract test) confirming newest session appears first.
- Frontend Jest/Cypress test verifying UI shows latest entry at index 0.
- Manual QA checklist item in dark/light themes.

**Dependencies**
- None beyond existing trading analytics API.

## Phase 2 – Dark-Mode Chart Contrast

**Implementation Notes**
- Introduce chart-specific CSS variables (e.g., `--chart-axis-label`, `--chart-grid-line`).
- Update dark-theme palette to high-contrast colors.
- Verify Ant Design theme overrides don’t clash with Recharts default styles.

**Baseline Snapshot (Oct 11, 2025)**
- Current dark-mode `History` tab screenshot captured (see `ui_snap/history_dark_pre_phase2.png`) highlighting low-contrast axis labels and tooltip timestamps.
- `AnalyticsDashboard` relies on Recharts defaults; axis tick fill inherits `currentColor`, resulting in muted gray over dark navy background.
- Ant Design dark theme defines `--color-text-secondary` at low opacity; reuse or override with higher contrast for chart contexts.

**Status Update (Oct 11, 2025 – evening)**
- Introduced chart-specific theme tokens in `frontend/src/styles.css` (grid, axis, tooltip, positive/negative series) with tailored light/dark values.
- Updated `AnalyticsDashboard` to consume those variables for axes, gradients, tooltips, and series colors, restoring legibility for timestamps in dark mode without regressing the light theme.
- Added Vitest coverage (`frontend/src/components/__tests__/AnalyticsDashboard.test.tsx`) that renders the dashboard and asserts Recharts primitives bind to the new CSS variables.
- Follow-up: capture an updated dark-mode analytics screenshot for `ui_snap/` once a browser session is available (blocked in headless CI for now).

**Validation**
- Visual diff (Percy/Chromatic) or screenshot comparison.
- [x] Automated Vitest coverage verifying CSS variables resolve for both themes.
- Manual QA pass on dashboard/chart with real data.

**Dependencies**
- Access to theme context and chart component styling hooks.

## Phase 3 – Analytics Export (CSV / Excel)

**Implementation Notes**
- Backend endpoint: `GET /api/analytics/export?format=csv&range=<...>`.
  - Stream CSV using `csv.DictWriter` to avoid large in-memory payloads.
  - Optional Excel support: convert dataset to DataFrame and export with `openpyxl`.
- Frontend: add Export button with busy state, success toast, and error handling.
- Include metadata headers (timestamp range, strategy ID) in the file.

**Status Update (Oct 11, 2025 – late evening)**
- Added `/api/analytics/export` endpoint guarded by existing auth, streaming CSV with metadata, metrics, and timeline rows plus filename timestamping.
- Frontend `AnalyticsDashboard` now exposes an "Export CSV" action that requests the file, triggers a browser download, and surfaces success/failure via Ant Design `message` notices.
- Automated coverage: backend pytest validates CSV headers/content-disposition and unsupported formats; Vitest suite mocks the download flow to ensure UI wiring and object URL handling.
- Follow-up: document endpoint usage in deployment guide and capture manual QA notes once snapshot is updated.

**Hotfix (Oct 11, 2025 – 23:15 UTC)**
- Resolved a backend startup regression caused by referencing a non-existent `AnalyticsHistoryStatus` schema in the CSV export helper. The service now relies on the existing `AnalyticsDataStatus` model and accepts any `Sequence` of sessions to satisfy stricter typing.
- Added defensive type tweaks to the helper to prevent future static-analysis breakages and verified `tests/test_analytics_export.py` passes locally.

**Validation**
- Backend test verifies content disposition and sample rows.
- Frontend test ensures button triggers download and disables while loading.
- Manual QA using real data to confirm spreadsheet opens correctly.

**Dependencies**
- Authentication middleware (reuse existing JWT flow).
- Large dataset handling: consider pagination or background job if needed.

## Phase 4 – Documentation & Observability

**Implementation Notes**
- Update `docs/deployment.md` and relevant READMEs with new endpoints/env vars.
- Add runbooks for export troubleshooting and chart theming.
- Instrument monitoring to track export duration, error rates, and dark-mode toggles.

**Validation**
- Sign-off from operations on documentation accuracy.
- Dashboard alerts set for export failure spikes.

**Dependencies**
- Access to logging/monitoring stack (e.g., CloudWatch, Sentry, Datadog).

**Status Update (Oct 12, 2025 – morning)**
- Refreshed `docs/deployment.md` with analytics export usage guidance, authentication requirements, and operational notes following the hotfix.
- Added a remediation summary to this roadmap so future phases understand the regression context.
- Instrumented the analytics export service with structured success/failure logs that capture duration, record counts, and range metadata.
- Authored `docs/runbooks/analytics-export.md` detailing monitoring thresholds, remediation steps, and escalation paths.

## CI/CD Pipeline Blueprint

### Development Laptop (WSL Ubuntu)
- Install pre-commit or pre-push hooks running `pnpm lint`, `pnpm test`, and `pytest`.
- Document environment setup in `docs/DEVELOPER_GUIDE.md`.

### GitHub Actions Workflow
1. **lint-and-test** (trigger on push/PR)
   - Setup Python → `pip install -e .[dev]` → `pytest`.
   - Setup Node → `pnpm install` → `pnpm lint` → `pnpm test -- --runInBand`.
   - Upload coverage artifacts.
2. **preprod-deploy** (manual approval after tests)
   - Build Docker images or production bundles.
   - Deploy using current pre-prod script with testing account env file.
   - Run automated smoke test that places a five-minute trade and validates dashboards.
3. **production-deploy** (manual approval after preprod success)
   - Connect to AWS Ubuntu VM (SSH/OIDC).
   - Run `scripts/deploy_prod.sh`.
   - Execute health checks (API heartbeat, websocket, UI ping).

### Environment Guidance
- Pre-prod runs on the same laptop; consider automating smoke script and publishing results back to Actions.
- Production uses AWS VM; store secrets in Parameter Store/Secrets Manager and aim for zero-downtime restarts.
- Enforce branch protection: green CI, reviewer approvals, up-to-date merges.
- Tag releases (`vYYYY.MM.DD`) after successful production deploy.

## Deliverables Checklist
- [x] Backend ordering logic updated and covered by tests.
- [x] Dark-mode color tokens applied and validated.
- [x] Export endpoint and UI integrated, with download tests.
- [x] Documentation refreshed and observability hooks in place.
- [ ] CI/CD workflow merged and branch protection enabled.

Track progress with issue labels (e.g., `phase-1`, `phase-2`) and summarize milestones in release notes.
