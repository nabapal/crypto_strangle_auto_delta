# Production Deployment Requirements

## Goals
- Run the entire application stack (backend, frontend, supporting services) in Docker containers suitable for production use on Linux hosts.
- Keep observability self-contained by streaming backend JSON logs into SQLite and surfacing them through the built-in dashboard viewer—no external ELK stack required.
- Preserve trading database and log state across container rebuilds/restarts by mounting the SQLite database and shared log directories from the host.
- Provide an automated script that updates the codebase from GitHub, handles local modifications safely, rebuilds images, and restarts the stack in one command.

## Containerized Stack Overview
- **Backend (FastAPI)**: Multi-stage Docker image, exposes port 8001, reads configuration via environment variables and `.env.prod`, emits structured JSON logs to stdout. Mount `./data` host directory to `/app/data` for SQLite persistence and `./logs` to `/app/logs` for file-based log tailing. Background services (`BackendLogTailService`, `BackendLogRetentionService`) must start automatically with the app.
- **Frontend (Vite/React + nginx)**: Multi-stage Docker image producing static assets served by nginx in the runtime container. Expose port 5173 internally; publish port 80 (or place behind an edge load balancer) and configure nginx to proxy `/api` to backend while serving the SPA (including the built-in log viewer tab).
- **Reverse proxy / TLS termination**: Handled by the nginx runtime container for HTTP; layer an external load balancer or CDN in front of port 80/443 for TLS as required by the hosting environment.
- **Networking**: Compose-defined bridge network (`app-net`) connecting all services. Only the reverse proxy is exposed to the host; internal services communicate via container aliases. Backend and frontend containers share the mounted `logs/` directory so the tail service can ingest backend output.

## Environment & Configuration
- Store secrets in `.env.prod` (not committed) referenced by docker-compose. Provide `.env.prod.example` as template.
- Backend environment variables must include
  - `DATABASE_URL=sqlite:////app/data/delta_trader.db`
  - `LOG_LEVEL` (default `INFO`) to manage verbosity for structured JSON logs
  - `BACKEND_LOG_INGEST_ENABLED=true` to run the tail/retention services in production
  - `BACKEND_LOG_PATH=/app/logs/backend.log` (match mounted file path)
  - `BACKEND_LOG_POLL_INTERVAL`, `BACKEND_LOG_BATCH_SIZE`, `BACKEND_LOG_RETENTION_DAYS` (default 7) to control ingestion cadence and retention window
  - Optional `LOG_INGEST_API_KEY` for protecting `/api/logs/batch`
  - Delta Exchange credentials and correlation ID policies as needed
- Frontend build uses `VITE_API_BASE_URL` pointing to the nginx gateway (e.g., `https://your-domain/api`) and must set `VITE_ENABLE_API_DEBUG=false` for production builds.
- Ensure the backend process writes JSON logs to `/app/logs/backend.log` (symlink or `LOG_PATH` override) so the tailer can stream them into SQLite.

## Persistence and Volumes
- Host directory bindings:
  - `./data` → `/app/data` (SQLite DB, analytics exports).
  - `./logs` → `/app/logs` (shared between backend container and host for log tailing, retention, and optional archival/rotation).
- Ensure host directories exist with appropriate permissions before running compose. Log files should be writable by the container user so the tailer can detect rotations.
- Docker volumes for transient components (e.g., `node_modules` cache) as needed.
- Consider log rotation policies at the host level (e.g., `logrotate`) to cap raw file size; retention service ensures SQLite history adheres to `BACKEND_LOG_RETENTION_DAYS`.

## Automation Script Requirements
- Linux shell script located under `scripts/deploy_prod.sh`, executable.
- Responsibilities:
  1. Navigate to repository directory.
  2. Detect local git changes; stash with timestamped label before pulling.
  3. Checkout target branch (`master`), fetch, and reset to remote.
  4. Run `docker compose -f docker-compose.prod.yml down --remove-orphans`.
  5. Build/pull required images (`backend`, `frontend`, optional reverse proxy`).
  6. Start stack via `docker compose ... up -d` and display status.
  7. Output reminders about stashed work, confirm log tailer background tasks are healthy, and note how to inspect the built-in log viewer.
- Optional enhancements: health checks, rollback instructions, pruning of old images, logging of deployment timestamp.

## Deliverables
1. `docker-compose.prod.yml` describing all services, volumes, networks, healthchecks, and log-sharing mounts.
2. Dockerfiles under `docker/` for backend and frontend/nginx (no external log shipper required).
3. `.env.prod.example` documenting required environment variables, including log ingestion and retention controls.
4. Deployment script `scripts/deploy_prod.sh` with usage instructions and post-deploy verification steps.
5. Documentation updates (`docs/deployment.md`) covering setup, secrets management, backup strategy, log retention settings, and troubleshooting the self-contained log viewer.

## Open Questions
- Choice of reverse proxy (nginx vs. Traefik) and TLS certificate management.
- Logging exports beyond SQLite are out of scope for initial launch; revisit if regulatory retention requirements exceed `BACKEND_LOG_RETENTION_DAYS`.
- Monitoring/alerting integration (Prometheus, uptime checks, log anomaly detection) remains a future enhancement; document correlation-ID propagation strategy when upstream clients supply them.
