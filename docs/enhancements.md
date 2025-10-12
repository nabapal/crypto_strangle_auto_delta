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

### 1. Local Quality Gates
- Install a `pre-commit` hook that runs `pnpm lint`, `pnpm test -- --runInBand`, `pytest`, and `ruff` (once adopted) before allowing commits.
- Mirror hook commands inside `scripts/dev_check.sh` so developers can invoke checks manually when the hook is bypassed.
- Document the hook bootstrap steps and troubleshooting tips in `docs/DEVELOPER_GUIDE.md`.

### 2. Branch & Release Strategy
- Adopt `master` as the protected release branch and use short-lived feature branches (`feature/*`, `bugfix/*`).
- Require pull requests to pass CI, receive at least one review, and stay up to date with `master` before merging.
- Create annotated tags (`vYYYY.MM.DD[-patch]`) immediately after production deployments and publish release notes linking to the enhancements checklist.

### 3. GitHub Actions Workflow Suite
1. **lint-and-test** (`on: push` to PR branches, `on: pull_request`)
   - Checkout with submodules (if added) and enable pnpm caching via `pnpm/action-setup`.
   - Stage Python environment: `pip install -e backend[dev]` inside the job workspace; cache `.venv` or `pip` dir.
   - Run backend checks: `pytest --maxfail=1 --disable-warnings`, `ruff check backend` (placeholder until adopted).
   - Stage Node environment: `pnpm install --frozen-lockfile` with caching.
   - Run frontend checks: `pnpm lint`, `pnpm test -- --runInBand --coverage`.
   - Collect coverage artifacts (`coverage.xml`, `lcov.info`) and publish to the build summary.
2. **docker-build** (`needs: lint-and-test`, runs on `push` to `master` and manual `workflow_dispatch`)
   - Build backend and frontend images using `docker/backend.Dockerfile` and `docker/frontend.Dockerfile`.
   - Scan images with Trivy and fail on critical vulnerabilities.
   - Push images to Amazon ECR (or GHCR) tagged with commit SHA and release tag.
3. **preprod-deploy** (`needs: docker-build`, gated by environment protection rule)
   - Fetch secrets from GitHub OIDC → AWS IAM role to pull environment variables from SSM Parameter Store.
   - Deploy the freshly built images to the pre-production ECS/Fargate service or docker-compose host.
   - Run smoke tests: invoke `/api/trading/heartbeat`, `/api/analytics/history`, and execute a lightweight websocket connect-test script.
   - Open an issue automatically if smoke tests fail (reference the deployment run).
4. **production-deploy** (`needs: preprod-deploy`, manual approval)
   - Reuse the published images (no rebuild) and update the production service.
   - Execute post-deploy checks: API heartbeat, frontend availability via Playwright ping, analytics export dry-run.
   - Notify Slack/Teams channel with deployment metadata and links to logs.

### 4. Observability & Rollback Hooks
- Emit structured logs during each pipeline step (build, deploy, smoke tests) and ship them to CloudWatch/Sentry.
- Capture pre/post-deployment metrics (error rate, latency) and automatically roll back if thresholds trip during a configurable canary window.
- Maintain a `scripts/rollback_prod.sh` helper that redeploys the previous tagged release.

### 5. Secret & Configuration Management
- Store API keys and database credentials in AWS SSM or Secrets Manager; grant GitHub Actions access via scoped IAM roles.
- Use `.env.preprod` and `.env.prod` templates checked into the repo with placeholder values and document required parameters.
- Rotate secrets quarterly and ensure the rotation plan is reflected in runbooks.

### 6. Deliverables & Timeline
- **Week 1:** Finalize hooks, update developer guide, enable branch protection rules.
- **Week 2:** Implement `lint-and-test` and `docker-build` workflows with caching and reporting.
- **Week 3:** Stand up preprod deployment job, smoke tests, and environment protection gates.
- **Week 4:** Wire production deployment approval flow, post-deploy checks, and notification integration. Tag the first automated release and update release notes.

Revisit this plan quarterly to accommodate new services, infrastructure changes, or compliance requirements.

## Deliverables Checklist
- [x] Backend ordering logic updated and covered by tests.
- [x] Dark-mode color tokens applied and validated.
- [x] Export endpoint and UI integrated, with download tests.
- [x] Documentation refreshed and observability hooks in place.
- [ ] CI/CD workflow merged and branch protection enabled.

Track progress with issue labels (e.g., `phase-1`, `phase-2`) and summarize milestones in release notes.
