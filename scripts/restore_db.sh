#!/usr/bin/env bash
# Restore a backup produced by backup_db.sh.
#
# Default mode restores into a throwaway database (<db>_restore_test) so you
# can verify a backup is actually restorable without touching live data —
# run this on a schedule as a restore drill, not just when disaster strikes.
#
# Connects directly via psql at POSTGRES_HOST:POSTGRES_PORT — works whether
# Postgres is a local native install or a docker-compose container
# publishing its port to the host.
#
# Usage:
#   ./scripts/restore_db.sh backups/Ga_Petrol_Bunk_20260830_020000.sql.gz
#   ./scripts/restore_db.sh --force-live backups/Ga_Petrol_Bunk_20260830_020000.sql.gz
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

FORCE_LIVE=0
if [ "${1:-}" = "--force-live" ]; then
  FORCE_LIVE=1
  shift
fi

BACKUP_FILE="${1:?Usage: restore_db.sh [--force-live] <backup-file.sql.gz>}"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "restore_db.sh: $BACKUP_FILE not found" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

: "${POSTGRES_USER:?POSTGRES_USER not set in .env}"
: "${POSTGRES_DB:?POSTGRES_DB not set in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD not set in .env}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

# pg_dump/psql aren't always on PATH — e.g. the EDB installer for macOS
# (/Library/PostgreSQL/<version>/bin) doesn't add itself to PATH by default.
# Fall back to the newest such install if the plain command isn't found.
find_pg_bin() {
  local bin_name="$1"
  if command -v "$bin_name" >/dev/null 2>&1; then
    command -v "$bin_name"
    return
  fi
  local candidate
  candidate="$(ls -d /Library/PostgreSQL/*/bin/"$bin_name" 2>/dev/null | sort -V | tail -1)"
  if [ -n "$candidate" ]; then
    echo "$candidate"
    return
  fi
  echo "restore_db.sh: $bin_name not found on PATH or under /Library/PostgreSQL/*/bin" >&2
  exit 1
}
PSQL="$(find_pg_bin psql)"
export PGPASSWORD="$POSTGRES_PASSWORD"

psql_admin() {
  "$PSQL" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 "$@"
}

if [ "$FORCE_LIVE" = "1" ]; then
  target_db="$POSTGRES_DB"
  echo "!! LIVE RESTORE into '$target_db' — this OVERWRITES current data."
  read -r -p "Type the database name to confirm: " confirm
  if [ "$confirm" != "$target_db" ]; then
    echo "Confirmation did not match, aborting." >&2
    exit 1
  fi
  echo "Dropping and recreating $target_db..."
  psql_admin -c "DROP DATABASE IF EXISTS \"$target_db\";" -c "CREATE DATABASE \"$target_db\";"
else
  target_db="${POSTGRES_DB}_restore_test"
  echo "Restoring into throwaway database '$target_db' (live data untouched)."
  psql_admin -c "DROP DATABASE IF EXISTS \"$target_db\";" -c "CREATE DATABASE \"$target_db\";"
fi

echo "Loading $BACKUP_FILE into $target_db..."
gunzip -c "$BACKUP_FILE" | "$PSQL" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$target_db" -v ON_ERROR_STOP=1 -q

table_count=$("$PSQL" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$target_db" -t -A \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';")

echo "Restore OK: $target_db has $table_count tables in the public schema."

if [ "$FORCE_LIVE" = "0" ]; then
  echo "Cleaning up throwaway database $target_db..."
  psql_admin -c "DROP DATABASE \"$target_db\";"
fi
