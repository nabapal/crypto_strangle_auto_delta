# Advanced Analytics Experience Overhaul

_Last updated: 2025-10-08_

## 1. Objectives

- Deliver deeper visibility into live and historical trading performance.
- Provide configurable filters (date range, strategy selection) to explore analytics across sessions.
- Surface advanced trade statistics: streaks, averages, extrema, drawdown.
- Introduce a branded welcome experience with user context and quick KPIs.
- Add critical alerting with acknowledgement workflow for operational awareness.
- Enhance the log viewer with summary analytics for faster diagnostics.

## 2. Scope Overview

| Area | Key Deliverables |
| --- | --- |
| Advanced Analytics UI | KPI grid overhaul, filter controls, streak & drawdown widgets, richer charts, trade timeline |
| Analytics Backend | Expanded metrics pipeline, historical snapshot endpoint, new schemas/tests |
| Welcome Page | Landing view with credentials badge, run-state highlights, themed layout |
| Notification Center | Critical error feed, mark-as-read API, bell/drawer UX |
| Log Viewer Summary | Aggregated counts, trends, quick filters, export support |
| Documentation & QA | Metric definitions, migrations, automated tests, deployment checklist |

## 3. Current State Assessment

- `frontend/src/components/AnalyticsDashboard.tsx` renders limited KPIs and a single PnL line chart without filtering.
- Analytics data stems from `AnalyticsService.latest_snapshot`, which only returns cached KPIs and raw PnL history.
- Dashboard routing is tab-based (`frontend/src/pages/Dashboard.tsx`); no welcome route exists.
- Log viewer already supports filtering but lacks aggregated insights and notification surfaces.

## 4. Functional Requirements

### Advanced Analytics Enhancements

- Date range selector (preset + custom) and strategy dropdown.
- Metrics: days running, trade counts, average profit/loss per trade, split averages for winners/losers, consecutive win/loss streaks, max gain/loss, max drawdown, average gain per winning trade, average loss per losing trade.
- Charts: cumulative PnL, drawdown curve, rolling win rate, trades histogram.
- Trade timeline with execution metadata and tooltips linking to raw order data.
- Auto refresh with stale-data warnings when backend errors occur.

### Welcome Page

- Introduce `/welcome` route with hero banner, environment badge, active session summary, quick links.
- Display authenticated user info (or placeholder credentials) and highlight strategy KPIs.
- Theme alignment with "Delta Strangle Control Plane" branding.

### Notifications

- Backend endpoint to fetch unread critical error events and mark them as read.
- Frontend notification bell with badge count, drawer listing alerts, mark-as-read controls, and deep links to logs.
- Realtime updates via polling or server-sent events.

### Log Viewer Summary

- Aggregated analytics (log volume per level, most common events, last error time) with quick filters.
- Visualization (bar chart/sparkline) above the table.
- Optional CSV/JSON export of filtered logs.

## 5. Architecture & Data Model Changes

### Backend

- **Analytics metrics**: Extend `TradeAnalyticsSnapshot` payload or introduce dedicated tables to capture trade outcomes (win/loss flags, PnL per trade). Add SQLAlchemy models & migrations.
- **Calculations**: Implement helper functions for streaks, averages, drawdown using window queries or Python aggregation.
- **Historical API**: New endpoint (e.g., `GET /analytics/history`) accepting `strategy_id`, `start`, `end`, `interval`.
- **Notifications**: New table `critical_alerts` (id, level, message, logged_at, read_at, read_by). Expose `/alerts/critical` (GET) and `/alerts/{id}/read` (POST).
- **Log summary**: Extend `/logs/backend` response or create `/logs/backend/summary` returning counts, trends, and last occurrence timestamps.
- **Testing**: Add pytest coverage for analytics computations, alert APIs, and log summaries.

### Frontend

- **Routing**: Integrate React Router, set `WelcomePage` as default route, preserve dashboard tabs.
- **State management**: Expand React Query usage with derived selectors for analytics filters.
- **Charts**: Build reusable chart components (`PnLChart`, `DrawdownChart`, `WinRateChart`, `TradeHistogram`).
- **KPI grid**: New component to display metrics with colored badges and tooltips.
- **Notifications**: Layout header integrates bell icon, using Ant Design notification/drawer components.
- **Log summary**: Prepend summary cards to `LogViewer` with quick filter actions.
- **Styling**: Update `ConfigProvider` theme tokens, add global styles for hero layout on welcome page.
- **Testing**: React Testing Library coverage for new components and flows.

## 6. Implementation Phases

1. **Data Foundations**
   - Design migrations for trade metrics & alerts.
   - Implement backend analytics calculators and history endpoint.
   - Backfill existing session data (script).

2. **API Layer**
   - Build notification and log-summary endpoints.
   - Extend `AnalyticsResponse` schema and update clients.

3. **Frontend Framework**
   - Introduce routing, welcome page scaffold, theme updates.
   - Implement notification center shell.

4. **Advanced Analytics UI**
   - Add filters, KPI grid, charts, timeline.
   - Integrate with new APIs and ensure responsive layout.

5. **Log Viewer Enhancements**
   - Render summary cards/charts; implement export and quick filters.

6. **Testing & Documentation**
   - Write automated tests across stack, add Storybook examples (optional).
   - Update docs and prepare deployment checklist.

## 7. Detailed Task Checklist

### Backend Checklist

- [ ] Draft and apply Alembic migrations for trade metrics & alert acknowledgements.
- [ ] Extend `AnalyticsService` with new computations and caching strategy.
- [ ] Implement `GET /analytics/history` with pagination and aggregation options.
- [ ] Add helper to compute drawdown and streaks from trade ledger.
- [ ] Expose `GET /alerts/critical` & `POST /alerts/{id}/read` endpoints.
- [ ] Update log API to emit summary analytics.
- [ ] Add pytest coverage and fixtures for new data shapes.
- [ ] Document new environment variables (`ALERT_POLL_INTERVAL`, etc.).

### Frontend Checklist

- [ ] Introduce React Router and Welcome page component.
- [ ] Update layout header to include global navigation and notifications bell.
- [ ] Build analytics filter bar (date range picker, strategy dropdown, auto-refresh toggle).
- [ ] Create KPI grid component supporting tooltips and trend comparisons.
- [ ] Implement charts for PnL, drawdown, win rate, and trade histogram.
- [ ] Add trade timeline with expandable rows showing order details.
- [ ] Integrate notification drawer with mark-as-read mutation.
- [ ] Enhance Log Viewer with summary widgets and export button.
- [ ] Update styling tokens and ensure accessibility contrast.
- [ ] Add unit/integration tests for new components and flows.

### DevOps & Release Checklist

- [ ] Update `.env.example` with new configuration keys.
- [ ] Create migration & backfill runbooks.
- [ ] Prepare rollout plan (staging validation, smoke scripts, monitoring dashboards).
- [ ] Document analytics metric definitions in `/docs`.
- [ ] Communicate changes to trading operations team and gather feedback loop.

## 8. Risks & Mitigations

- **Complex computations on large datasets** → Use SQL aggregates, add DB indices, cache snapshots.
- **UI performance with large history** → Implement pagination/virtualization, limit chart points via down-sampling.
- **Alert fatigue** → Allow filter preferences and snooze options in future iterations.
- **Authentication gaps for welcome page credentials** → Integrate with existing auth provider or mock safely until SSO available.

## 9. Success Metrics

- Time-to-insight: operators can identify top issues within 2 minutes using dashboard.
- Reduced reliance on raw logs: 50% decrease in manual log searches for routine issues.
- Adoption: majority of daily users start on the welcome page (tracked via telemetry events).
- Error response time: average acknowledgement < 10 minutes for critical alerts.

---

This document should guide implementation planning, cross-team coordination, and future iteration discussions for the analytics UI overhaul and related UX improvements.
