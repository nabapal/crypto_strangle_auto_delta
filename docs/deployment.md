# Production Deployment Guide

This guide describes how to deploy the Delta Strangle Control Plane to a production Linux host using Docker Compose, with a self-contained logging pipeline and no external ELK dependencies. It consolidates the production requirements alongside the hands-on procedure so you have a single source of truth for preparing and operating the stack.

## Goals & scope
- Run the entire backend, frontend, and supporting services in Docker containers suited for Linux production hosts.
- Keep observability self-contained by streaming backend JSON logs into SQLite and surfacing them through the built-in dashboard log viewer—no external ELK stack required.
- Preserve trading state and log history across rebuilds by mounting the SQLite database and shared log directories from the host.
- Provide an automated script that safely updates the codebase from GitHub, handles local modifications, rebuilds images, and restarts the stack in one command.

## Containerized stack overview
- **Backend (FastAPI)**: Multi-stage build that exposes port 8001, reads configuration from `.env.prod`, emits structured JSON logs to `/app/logs/backend.log`, and launches the `BackendLogTailService` and `BackendLogRetentionService` automatically.
- **Frontend (Vite/React + nginx)**: Multi-stage build that serves the compiled SPA via nginx on port 80 (publishing only the reverse proxy). nginx proxies `/api` traffic to the backend on the internal Docker network.
- **Reverse proxy / TLS termination**: nginx handles HTTP responses; layer an external load balancer or CDN in front of port 80/443 when you need full TLS termination.
- **Networking**: Services join the Compose-defined bridge network (`app-net`). Only nginx is published to the host; backend routes remain internal. Backend and frontend share the mounted `logs/` directory so the tail services can ingest output.

## Prerequisites
- Docker Engine 24.x or later and Docker Compose plugin 2.x installed.
- Git credentials with read access to the repository.
- Host directories `data/` and `logs/` (created automatically by the deploy script) residing on durable storage.
- Outbound internet access for pulling container base images and Delta Exchange APIs.

## Configuration
1. **Clone the repository** on the target host:
   ```bash
   git clone https://github.com/nabapal/crypto_strangle_auto_delta.git
   cd crypto_strangle_auto_delta
   ```
2. **Create a production environment file** by copying the template and filling in secrets:
   ```bash
   cp .env.prod.example .env.prod
   ```
   Populate at minimum:
   - `DATABASE_URL=sqlite+aiosqlite:////app/data/delta_trader.db`
   - `LOG_INGEST_API_KEY` (optional protection for `/api/logs/batch`)
   - `DELTA_API_KEY` / `DELTA_API_SECRET`
   - `ALLOWED_ORIGINS` with the production frontend URL
   - `APP_UID` / `APP_GID` matching the host user that owns the repository (prevents bind-mount permission errors)
   - `VITE_API_BASE_URL` set to `https://<your-domain>/api`
   - `VITE_ENABLE_API_DEBUG=false` to disable API inspector banners in production builds
   - `LOG_LEVEL=INFO` (or stricter) to control structured JSON verbosity
   - `BACKEND_LOG_INGEST_ENABLED=true` to ensure the log tail/retention services run in production
   - `BACKEND_LOG_PATH=/app/logs/backend.log` (must align with the mounted log file path)
   - `BACKEND_LOG_POLL_INTERVAL`, `BACKEND_LOG_BATCH_SIZE`, and `BACKEND_LOG_RETENTION_DAYS=7` to govern ingestion cadence and history window
   - Any required Delta Exchange correlation ID policies or additional secrets referenced by the backend

3. **Prepare host storage** (if not using the deploy script):
   ```bash
   mkdir -p data logs
   ```

## Persistence & volumes
- Bind `./data` to `/app/data` to persist the SQLite database, analytics exports, and log archives across container rebuilds.
- Bind `./logs` to `/app/logs` so the backend can emit JSON logs and the tailer can stream them into SQLite.
- Ensure the Docker daemon user has read/write access to these directories. The deploy script will attempt to `chown` them to `APP_UID:APP_GID` after sourcing `.env.prod`.
- Implement host-level log rotation (e.g., `logrotate`) if you want to cap raw file size; the retention service keeps the SQLite history aligned with `BACKEND_LOG_RETENTION_DAYS`.

## Deploying with the automation script
Run the deployment script from the repository root:
```bash
./scripts/deploy_prod.sh
```
The script performs the following actions:
1. Verifies `docker-compose.prod.yml` and `.env.prod` exist and ensures `data/` and `logs/` are present.
2. Stashes any local git changes with a timestamped label.
3. Checks out `master`, fetches the latest code, and resets to `origin/master`.
4. Stops existing containers (`docker compose down --remove-orphans`).
5. Builds the backend and frontend images (`docker compose build --pull`).
6. Starts the stack (`docker compose up -d`) and shows service status.
7. Prints reminders about stashed work, confirms how to verify the log tailer/background tasks, and points to the built-in log viewer for validation.

Optional enhancements for the script include adding health checks, rollback guidance, pruning old images, and logging deployment timestamps for audit trails.

## Containerized stack & networking
- **Backend** (`delta-strangle-backend:prod`)
  - FastAPI app built via a multi-stage Dockerfile and exposed on port 8001.
  - Mounts `./data:/app/data` for SQLite state and `./logs:/app/logs` for JSON log output.
  - Writes structured logs to `/app/logs/backend.log`; `BackendLogTailService` and `BackendLogRetentionService` stream them into SQLite and enforce retention.
- **Frontend** (`delta-strangle-frontend:prod`)
  - Builds the Vite React SPA and serves it with nginx on port 80.
  - Proxies `/api/` traffic to the backend container over the internal Docker network while exposing only the SPA and reverse proxy to the host.
- **Networking**
  - All services join the `app-net` bridge network in `docker-compose.prod.yml` and communicate via container aliases.
  - Only TCP port 80 is published externally; place a dedicated reverse proxy, load balancer, or CDN in front for TLS termination if required.
  - The shared `logs/` mount keeps observability self-contained without external ELK dependencies.

## Observability
- **Log ingestion**: Backend logs emitted to `/app/logs/backend.log` are tailed and persisted in the `backend_logs` table within `./data/delta_trader.db`.
- **Retention**: `BACKEND_LOG_RETENTION_DAYS` defaults to 7 days and can be set via `.env.prod` to adjust the SQLite retention window.
- **Log viewer**: Access the web UI at `https://<your-domain>/` and open the “Log Viewer” tab to query logs by level, event, correlation ID, date range, etc.
- **Raw files**: `/app/logs/backend.log` remains on disk for troubleshooting; incorporate host-level rotation if desired (e.g., `logrotate`).

## Analytics exports
- **API endpoint**: `GET /api/analytics/export` streams a CSV snapshot of metrics and timeline events for the requested date range. Query parameters mirror the dashboard history filters (`start`, `end`, optional `preset`, `strategy_id`). Only the `format=csv` variant is enabled; other values return `422`.
- **Authentication**: The endpoint is protected by the same JWT middleware as the rest of the analytics API. Ensure front-end tokens are valid prior to triggering downloads.
- **Frontend flow**: The “Export CSV” button in the Advanced Analytics dashboard uses the endpoint above, shows a loading spinner, and prompts the browser to download files named `analytics-export-YYYYMMDD-HHMMSS.csv`.
- **Operational notes**: CSV files are generated on the fly and not stored on disk; schedule internal QA checks to confirm spreadsheet headers (`metadata`, `metrics`, `timeline`) match expectations after each deployment. A regression on Oct 11, 2025 highlighted the importance of keeping backend schema imports aligned—tests now guard the streaming helper, but keep an eye on application logs after each deploy to catch similar issues early.

## Maintenance
- **Updating code**: Re-run `./scripts/deploy_prod.sh` whenever new commits are available. The script automatically rebuilds images and restarts services.
- **Restoring stashed changes**: If the script stashed modifications, review them with `git stash list` and reapply using `git stash pop <name>`.
- **Backups**: Periodically back up the `data/` directory to protect historical trading state and ingested logs.
- **TLS**: Place an upstream nginx/Traefik instance or cloud load balancer in front of the stack to terminate HTTPS and forward traffic to port 80.

## Troubleshooting
- Check container status: `docker compose -f docker-compose.prod.yml ps`
- Follow backend logs: `docker compose -f docker-compose.prod.yml logs -f backend`
- Verify frontend build: `docker compose -f docker-compose.prod.yml logs -f frontend`
- Confirm log ingestion: query `backend_logs` table inside `data/delta_trader.db` (e.g., using `sqlite3`).

The stack deliberately excludes external log shippers and monitoring stacks; integrate them later if compliance requirements change.

## Deliverables checklist
1. `docker-compose.prod.yml` describing services, volumes, networks, and log-sharing mounts.
2. Backend and frontend Dockerfiles under `docker/` (no external log shipper required).
3. `.env.prod.example` documenting required environment variables, including log ingestion and retention controls.
4. Deployment script `scripts/deploy_prod.sh` with usage instructions and post-deploy verification steps.
5. Documentation updates (this guide) covering setup, secrets management, backup strategy, log retention, and troubleshooting.

## Open questions
- Decide on long-term reverse proxy (nginx vs. Traefik) and TLS certificate management strategy.
- Determine whether log exports beyond SQLite are needed if regulatory retention requirements exceed `BACKEND_LOG_RETENTION_DAYS`.
- Plan for monitoring and alerting integration (Prometheus, uptime checks, log anomaly detection) and document correlation-ID propagation when upstream clients supply them.
