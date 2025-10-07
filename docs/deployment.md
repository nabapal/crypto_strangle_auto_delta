# Production Deployment Guide

This guide describes how to deploy the Delta Strangle Control Plane to a production Linux host using Docker Compose, with a self-contained logging pipeline and no external ELK dependencies.

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
   - `VITE_API_BASE_URL` set to `https://<your-domain>/api`

3. **Prepare host storage** (if not using the deploy script):
   ```bash
   mkdir -p data logs
   ```
   Ensure the Docker daemon user has read/write access to these directories.

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
7. Prints reminders about stashed work and how to inspect container logs.

## Service topology
- **Backend** (`delta-strangle-backend:prod`)
  - Runs FastAPI on port 8001.
  - Mounted volumes: `./data:/app/data`, `./logs:/app/logs`.
  - Structured JSON logs are written to `/app/logs/backend.log` and ingested into SQLite via `BackendLogTailService` and `BackendLogRetentionService`.
- **Frontend** (`delta-strangle-frontend:prod`)
  - Builds the Vite React app and serves it through nginx on port 80.
  - Proxies `/api/` traffic to the backend service on the internal Docker network.

Both services are attached to the `app-net` bridge network defined in `docker-compose.prod.yml`. Externally, only TCP port 80 is published (configure a reverse proxy or load balancer for TLS termination as required).

## Observability
- **Log ingestion**: Backend logs emitted to `/app/logs/backend.log` are tailed and persisted in the `backend_logs` table within `./data/delta_trader.db`.
- **Retention**: `BACKEND_LOG_RETENTION_DAYS` defaults to 7 days and can be set via `.env.prod` to adjust the SQLite retention window.
- **Log viewer**: Access the web UI at `https://<your-domain>/` and open the “Log Viewer” tab to query logs by level, event, correlation ID, date range, etc.
- **Raw files**: `/app/logs/backend.log` remains on disk for troubleshooting; incorporate host-level rotation if desired (e.g., `logrotate`).

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
