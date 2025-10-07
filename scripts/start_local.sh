#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data"
DB_FILE="${DATA_DIR}/delta_trader.db"
BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOG_DIR="${ROOT_DIR}/logs"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"
LOG_API_KEY="${LOG_API_KEY:-local-dev-ingest-key}"
API_BASE_URL_DEFAULT="http://localhost:${BACKEND_PORT}/api"
API_BASE_URL="${API_BASE_URL:-${API_BASE_URL_DEFAULT}}"
LOG_ENDPOINT_DEFAULT="${API_BASE_URL%/}/logs/batch"
LOG_ENDPOINT="${LOG_ENDPOINT:-${LOG_ENDPOINT_DEFAULT}}"
DEFAULT_ALLOWED_ORIGIN="http://localhost:${FRONTEND_PORT}"
DEFAULT_ALLOWED_ORIGINS_JSON="[\"${DEFAULT_ALLOWED_ORIGIN}\"]"

printf '[info] Switching to project root %s\n' "${ROOT_DIR}"
cd "${ROOT_DIR}"

if [[ -z "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${ROOT_DIR}"
else
  export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH}"
fi

printf '\n[start] Preparing workspace at %s\n' "${ROOT_DIR}"
rm -f "${ROOT_DIR}/delta_trader.db" "${ROOT_DIR}/backend/delta_trader.db"
mkdir -p "${DATA_DIR}"
mkdir -p "${LOG_DIR}"

>"${BACKEND_LOG}"
>"${FRONTEND_LOG}"

printf '[info] Backend log -> %s\n' "${BACKEND_LOG}"
printf '[info] Frontend log -> %s\n' "${FRONTEND_LOG}"

export DATABASE_URL="sqlite+aiosqlite:///${DB_FILE}"
printf '[info] DATABASE_URL=%s\n' "${DATABASE_URL}"
export LOG_INGEST_API_KEY="${LOG_API_KEY}"
export LOG_INGEST_MAX_BATCH="${LOG_INGEST_MAX_BATCH:-100}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"
export ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-${DEFAULT_ALLOWED_ORIGINS_JSON}}"
export DEBUG_HTTP_LOGGING="${DEBUG_HTTP_LOGGING:-false}"
printf '[info] LOG_INGEST_API_KEY set (length=%s)\n' "${#LOG_INGEST_API_KEY}"
printf '[info] LOG_ENDPOINT=%s\n' "${LOG_ENDPOINT}"
printf '[info] ALLOWED_ORIGINS=%s\n' "${ALLOWED_ORIGINS}"

PY_ENV="${ROOT_DIR}/.venv/bin/activate"
if [[ ! -f "${PY_ENV}" ]]; then
  echo "[error] Python virtualenv not found at ${PY_ENV}. Run 'python -m venv .venv' and install deps." >&2
  exit 1
fi
source "${PY_ENV}"

cleanup() {
  printf '\n[stop] Shutting down services...\n'
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

printf '[start] Launching FastAPI backend on port %s\n' "${BACKEND_PORT}"
uvicorn backend.app.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" >>"${BACKEND_LOG}" 2>&1 &
BACKEND_PID=$!

# Ensure pnpm is available (pnpm adds itself in ~/.bashrc)
if [[ -f "${HOME}/.bashrc" ]]; then
  # shellcheck disable=SC1090
  source "${HOME}/.bashrc"
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "[error] pnpm not found. Install it (curl -fsSL https://get.pnpm.io/install.sh | sh) before running this script." >&2
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
    wait "${BACKEND_PID}" || true
  fi
  exit 1
fi

cd "${ROOT_DIR}/frontend"
if [[ ! -d node_modules ]]; then
  echo "[deps] Installing frontend dependencies with pnpm"
  pnpm install
fi

printf '[start] Launching frontend dev server on port %s\n' "${FRONTEND_PORT}"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-${API_BASE_URL}}"
export VITE_ENABLE_API_DEBUG="${VITE_ENABLE_API_DEBUG:-true}"
export VITE_ENABLE_REMOTE_LOGS="${VITE_ENABLE_REMOTE_LOGS:-true}"
export VITE_LOG_ENDPOINT="${VITE_LOG_ENDPOINT:-${LOG_ENDPOINT}}"
export VITE_LOG_API_KEY="${VITE_LOG_API_KEY:-${LOG_API_KEY}}"
export VITE_APP_VERSION="${VITE_APP_VERSION:-local-dev}"
export VITE_LOG_DEDUP_WINDOW="${VITE_LOG_DEDUP_WINDOW:-1000}"
export VITE_LOG_DEDUP_THRESHOLD="${VITE_LOG_DEDUP_THRESHOLD:-5}"
printf '[info] VITE_API_BASE_URL=%s\n' "${VITE_API_BASE_URL}"
printf '[info] VITE_LOG_ENDPOINT=%s\n' "${VITE_LOG_ENDPOINT}"
printf '[info] Remote telemetry=%s\n' "${VITE_ENABLE_REMOTE_LOGS}"

pnpm dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}" --strictPort >>"${FRONTEND_LOG}" 2>&1 &
FRONTEND_PID=$!

printf '\n[ready] Backend -> http://localhost:%s\n' "${BACKEND_PORT}"
printf '[ready] Frontend -> http://localhost:%s\n' "${FRONTEND_PORT}"
printf '[info] Press Ctrl+C to stop both services.\n\n'

wait
