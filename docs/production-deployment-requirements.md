# Production Deployment Requirements

## Goals
- Run the entire application stack (backend, frontend, supporting services) in Docker containers suitable for production use on Linux hosts.
- Keep observability self-contained by tailing backend logs into SQLite and exposing them through the built-in dashboard viewer.
- Preserve trading database state across container rebuilds/restarts by mounting the SQLite database directory from the host.
- Provide an automated script that updates the codebase from GitHub, handles local modifications safely, rebuilds images, and restarts the stack in one command.

## Containerized Stack Overview
- **Backend (FastAPI)**: Multi-stage Docker image, exposes port 8001, reads configuration via environment variables and `.env.prod`, emits JSON logs to stdout. Mount `./data` host directory to `/app/data` for SQLite persistence.
- **Frontend (Vite/React)**: Multi-stage Docker image producing static assets served by an nginx runtime container. Expose port 5173 (or behind reverse proxy). Configure nginx to proxy API traffic to backend.
- **Reverse proxy (optional)**: nginx or Traefik container terminating TLS and routing `/api` to backend, `/` to frontend.
- **Networking**: Compose-defined bridge network (`app-net`) connecting all services. Only reverse proxy and Kibana exposed to host; internal services communicate via container aliases.
- **Networking**: Compose-defined bridge network (`app-net`) connecting all services. Only the reverse proxy is exposed to the host; internal services communicate via container aliases. Backend and frontend containers mount the shared `logs/` directory so the log tailer can ingest backend output.

## Environment & Configuration
- Store secrets in `.env.prod` (not committed) referenced by docker-compose. Provide `.env.prod.example` as template.
- Backend environment variables to include `DATABASE_URL=sqlite:////app/data/delta_trader.db`, Delta credentials, logging settings, and correlation ID toggles.
- Frontend build uses `VITE_API_BASE_URL` pointing to reverse proxy or backend service name.
- Configure backend environment variables for the log tailer (`BACKEND_LOG_PATH`, `BACKEND_LOG_POLL_INTERVAL`, `BACKEND_LOG_BATCH_SIZE`, `BACKEND_LOG_RETENTION_DAYS`) to ensure the ingestion service runs automatically.

## Persistence and Volumes
- Host directory bindings:
  - `./data` → `/app/data` (SQLite DB, analytics exports).
  - `./logs` → `/app/logs` (shared between backend container and host for log tailing and archival).
- Ensure host directories exist with appropriate permissions before running compose.
- Docker volumes for transient components (e.g., `node_modules` cache) as needed.

## Automation Script Requirements
- Linux shell script located under `scripts/deploy_prod.sh`, executable.
- Responsibilities:
  1. Navigate to repository directory.
  2. Detect local git changes; stash with timestamped label before pulling.
  3. Checkout target branch (`master`), fetch, and reset to remote.
  4. Run `docker compose -f docker-compose.prod.yml down --remove-orphans`.
  5. Build/pull required images (`backend`, `frontend`, optional reverse proxy`).
  6. Start stack via `docker compose ... up -d` and display status.
  7. Output reminders about stashed work and next steps.
- Optional enhancements: health checks, rollback instructions, pruning of old images, logging of deployment timestamp.

## Deliverables
1. `docker-compose.prod.yml` describing all services, volumes, networks, and healthchecks.
2. Dockerfiles under `docker/` for backend, frontend, filebeat (and proxy if used).
3. `.env.prod.example` documenting required environment variables.
4. Deployment script `scripts/deploy_prod.sh` with usage instructions.
5. Documentation updates (`docs/deployment.md`) covering setup, secrets management, backup strategy, log retention, and troubleshooting.

## Open Questions
- Choice of reverse proxy (nginx vs. Traefik) and TLS certificate management.
- Logging exports beyond SQLite (e.g., nightly S3 archival) for compliance retention.
- Monitoring/alerting integration (Prometheus, uptime checks, log anomaly detection).
