#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/data"
DB_FILE="${DATA_DIR}/delta_trader.db"

if [[ -n "${1:-}" ]]; then
  DB_FILE="$1"
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "[error] sqlite3 is required to run this migration script"
  exit 1
fi

if [[ ! -f "${DB_FILE}" ]]; then
  echo "[error] Database file not found: ${DB_FILE}"
  exit 1
fi

backup="${DB_FILE}.bak-$(date +%s)"
cp "${DB_FILE}" "${backup}"
echo "[migrate] Backed up DB to ${backup}"

# Helper to check and add column
add_column_if_missing() {
  local table="$1"
  local column="$2"
  local definition="$3"

  if sqlite3 "${DB_FILE}" "PRAGMA table_info('${table}');" | awk -F'|' '{print $2}' | grep -qx "${column}"; then
    echo "[migrate] Column '${column}' already present in ${table}"
  else
    echo "[migrate] Adding column '${column}' to ${table}"
    sqlite3 "${DB_FILE}" "ALTER TABLE ${table} ADD COLUMN ${definition};"
  fi
}

TABLE="trading_configurations"
add_column_if_missing "${TABLE}" "call_option_price_min" "call_option_price_min FLOAT"
add_column_if_missing "${TABLE}" "call_option_price_max" "call_option_price_max FLOAT"
add_column_if_missing "${TABLE}" "put_option_price_min" "put_option_price_min FLOAT"
add_column_if_missing "${TABLE}" "put_option_price_max" "put_option_price_max FLOAT"

# Add strike_selection_mode column if missing (string, default 'delta')
add_column_if_missing "${TABLE}" "strike_selection_mode" "strike_selection_mode TEXT DEFAULT 'delta'"

# Optional: create indexes to speed up queries if desired
# (Not strictly necessary for small configs table, but harmless.)
sqlite3 "${DB_FILE}" "CREATE INDEX IF NOT EXISTS ix_trading_configurations_call_min ON ${TABLE}(call_option_price_min);"
sqlite3 "${DB_FILE}" "CREATE INDEX IF NOT EXISTS ix_trading_configurations_put_min ON ${TABLE}(put_option_price_min);"

echo "[migrate] Migration completed against ${DB_FILE}"