#!/usr/bin/env bash
# Nightly Postgres backup: dumps the configured DB directly via pg_dump
# (works whether Postgres is a local native install or a docker-compose
# container publishing its port to the host — either way it's reachable at
# POSTGRES_HOST:POSTGRES_PORT), gzips it, verifies the archive isn't
# corrupt, and prunes backups older than $RETENTION_DAYS. Meant to be run
# from a cron/launchd timer.
#
# Usage: ./scripts/backup_db.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

BACKUP_DIR="${BACKUP_DIR:-$SCRIPT_DIR/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [ ! -f .env ]; then
  echo "backup_db.sh: no .env found in $SCRIPT_DIR" >&2
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
  echo "backup_db.sh: $bin_name not found on PATH or under /Library/PostgreSQL/*/bin" >&2
  exit 1
}
PG_DUMP="$(find_pg_bin pg_dump)"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d_%H%M%S)"
dest="$BACKUP_DIR/${POSTGRES_DB}_${timestamp}.sql.gz"
tmp="$dest.tmp"

echo "[$(date -Iseconds)] Dumping $POSTGRES_DB@$POSTGRES_HOST:$POSTGRES_PORT -> $dest"

PGPASSWORD="$POSTGRES_PASSWORD" "$PG_DUMP" \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=plain \
  | gzip > "$tmp"

if [ ! -s "$tmp" ]; then
  echo "backup_db.sh: dump is empty, aborting" >&2
  rm -f "$tmp"
  exit 1
fi

if ! gzip -t "$tmp"; then
  echo "backup_db.sh: gzip archive failed integrity check, aborting" >&2
  rm -f "$tmp"
  exit 1
fi

mv "$tmp" "$dest"
echo "[$(date -Iseconds)] Wrote $(du -h "$dest" | cut -f1) -> $dest"

echo "Pruning backups older than $RETENTION_DAYS days in $BACKUP_DIR"
find "$BACKUP_DIR" -name "${POSTGRES_DB}_*.sql.gz" -mtime "+$RETENTION_DAYS" -print -delete

echo "[$(date -Iseconds)] Backup complete."
