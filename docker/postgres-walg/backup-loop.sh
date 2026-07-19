#!/bin/sh
set -eu

: "${PGDATA:=/var/lib/postgresql/data}"
: "${WALG_BACKUP_INTERVAL_SECONDS:=86400}"
: "${WALG_RETENTION_DAYS:=30}"
: "${WALG_S3_PREFIX:?WALG_S3_PREFIX must be set}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID must be set}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY must be set}"
: "${AWS_ENDPOINT:?AWS_ENDPOINT must be set}"

case "$WALG_BACKUP_INTERVAL_SECONDS:$WALG_RETENTION_DAYS" in
  *[!0-9:]* | :* | *: | 0:* | *:0) echo "Backup interval and retention days must be positive integers" >&2; exit 2 ;;
esac

while ! pg_isready -q; do
  echo "Waiting for Postgres before the WAL-G base backup..."
  sleep 2
done

while true; do
  echo "Starting WAL-G physical base backup"
  if wal-g backup-push "$PGDATA"; then
    cutoff="$(date -u --date="${WALG_RETENTION_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ)"
    echo "Applying WAL-G retention cutoff ${cutoff} (keeping at least one full backup)"
    if ! wal-g delete retain FULL 1 --after "$cutoff" --confirm; then
      echo "WAL-G retention failed; the next daily backup will retry it" >&2
    else
      echo "WAL-G retention completed successfully"
    fi
  else
    echo "WAL-G base backup failed; the next daily attempt remains scheduled" >&2
  fi
  sleep "$WALG_BACKUP_INTERVAL_SECONDS"
done
