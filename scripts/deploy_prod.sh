#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker-compose.prod.yml"
ENV_FILE="${REPO_ROOT}/.env.prod"

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "[deploy] docker-compose.prod.yml not found at ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[deploy] Missing ${ENV_FILE}. Copy .env.prod.example and populate secrets before deploying." >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/data" "${REPO_ROOT}/logs"

# export build arguments from .env.prod for docker compose
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

app_uid="${APP_UID:-1000}"
app_gid="${APP_GID:-1000}"
if ! chown -R "${app_uid}:${app_gid}" "${REPO_ROOT}/data" "${REPO_ROOT}/logs" 2>/dev/null; then
  echo "[deploy] Warning: unable to chown data/logs to ${app_uid}:${app_gid}. Ensure these directories are writable by the container user." >&2
fi

pushd "${REPO_ROOT}" >/dev/null

current_branch="$(git rev-parse --abbrev-ref HEAD)"
stash_name=""

if ! git diff --quiet || ! git diff --cached --quiet; then
  timestamp="$(date +"%Y%m%d-%H%M%S")"
  stash_name="deploy-${timestamp}"
  echo "[deploy] Local changes detected. Stashing as '${stash_name}'."
  git stash push --include-untracked -m "${stash_name}" >/dev/null
else
  echo "[deploy] No local changes detected."
fi

if [[ "${current_branch}" != "master" ]]; then
  echo "[deploy] Checking out master branch from ${current_branch}."
  git checkout master
fi

echo "[deploy] Fetching latest changes from origin/master."
git fetch origin master

echo "[deploy] Resetting local master to origin/master."
git reset --hard origin/master

echo "[deploy] Stopping existing containers (if any)."
docker compose -f "${COMPOSE_FILE}" down --remove-orphans

echo "[deploy] Building images with latest code."
docker compose -f "${COMPOSE_FILE}" build --pull backend frontend

# If host DB exists, run safe migrations before bringing containers up to avoid startup failures
db_filename="$(basename "${DATABASE_URL##*/}")"
host_db_path="${REPO_ROOT}/data/${db_filename}"
if command -v sqlite3 >/dev/null 2>&1 && [[ -f "${host_db_path}" ]]; then
  echo "[deploy] Found database at ${host_db_path}. Running safe migrations before starting containers."
  # Backup is handled inside migration script; call it with bash to be safe
  bash "${REPO_ROOT}/scripts/migrate_add_option_price_ranges.sh" "${host_db_path}" || {
    echo "[deploy] Migration failed against ${host_db_path}. Aborting deployment." >&2
    exit 1
  }
else
  echo "[deploy] No host DB found at ${host_db_path} or sqlite3 missing; skipping host migrations."
fi

echo "[deploy] Starting services."
docker compose -f "${COMPOSE_FILE}" up -d

echo "[deploy] Stack status:"
docker compose -f "${COMPOSE_FILE}" ps

# If database on host exists, perform safe backup and add 'strategy_id' column if missing.
db_filename="$(basename "${DATABASE_URL##*/}")"
host_db_path="${REPO_ROOT}/data/${db_filename}"
if command -v sqlite3 >/dev/null 2>&1 && [[ -f "${host_db_path}" ]]; then
  echo "[deploy] Found database at ${host_db_path}. Checking schema..."
  if ! sqlite3 "${host_db_path}" "PRAGMA table_info('backend_logs');" | awk -F'|' '{print $2}' | grep -qx "strategy_id"; then
    backup_path="${host_db_path}.bak-$(date +%s)"
    echo "[deploy] Backing up DB to ${backup_path}"
    cp "${host_db_path}" "${backup_path}"
    echo "[deploy] Adding 'strategy_id' column to backend_logs"
    sqlite3 "${host_db_path}" "ALTER TABLE backend_logs ADD COLUMN strategy_id TEXT;"
    sqlite3 "${host_db_path}" "CREATE INDEX IF NOT EXISTS ix_backend_logs_strategy_id ON backend_logs(strategy_id);"
  else
    echo "[deploy] 'strategy_id' already exists in backend_logs"
  fi
fi

popd >/dev/null

echo
if [[ -n "${stash_name}" ]]; then
  echo "[deploy] Local changes were stashed as '${stash_name}'. Retrieve them with: git stash pop ${stash_name}"
else
  echo "[deploy] No stashed work to restore."
fi

echo "[deploy] Verify backend log ingestion via the dashboard log viewer (Frontend > Log Viewer tab)."
echo "[deploy] Tail container logs if needed: docker compose -f ${COMPOSE_FILE} logs -f backend"
