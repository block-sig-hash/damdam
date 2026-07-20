#!/bin/sh
set -eu

: "${PGDATA:=/var/lib/postgresql/data}"
: "${WALG_BACKUP_INTERVAL_SECONDS:=86400}"
: "${WALG_RETENTION_DAYS:=30}"
: "${WALG_S3_PREFIX:?WALG_S3_PREFIX must be set}"
: "${AWS_ACCESS_KEY_ID:?AWS_ACCESS_KEY_ID must be set}"
: "${AWS_SECRET_ACCESS_KEY:?AWS_SECRET_ACCESS_KEY must be set}"
: "${AWS_ENDPOINT:?AWS_ENDPOINT must be set}"
# Optional: an Uptime Kuma push-monitor base URL, e.g.
# http://100.72.59.74:3001/api/push/<token> with no query string
# (infrastructure.md §11.5). Left unset in local/dev/test, where no
# monitoring stack exists -- the backup loop must never fail or block on
# this being absent or unreachable, since the backup itself succeeding is
# what matters, not the heartbeat side effect.
: "${KUMA_PUSH_URL:=}"

case "$WALG_BACKUP_INTERVAL_SECONDS:$WALG_RETENTION_DAYS" in
  *[!0-9:]* | :* | *: | 0:* | *:0) echo "Backup interval and retention days must be positive integers" >&2; exit 2 ;;
esac

send_heartbeat() {
  # Best-effort only: a Kuma outage or unreachable network must never fail
  # the backup loop itself, so failures here are logged, not propagated.
  [ -n "$KUMA_PUSH_URL" ] || return 0
  if curl -fsS -m 10 "${KUMA_PUSH_URL}?status=up&msg=$1&ping=" >/dev/null 2>&1; then
    echo "Kuma heartbeat sent"
  else
    echo "Kuma heartbeat request failed (non-fatal; backup result is unaffected)" >&2
  fi
}

while ! pg_isready -q; do
  echo "Waiting for Postgres before the WAL-G base backup..."
  sleep 2
done

while true; do
  echo "Starting WAL-G physical base backup"
  if wal-g backup-push "$PGDATA"; then
    send_heartbeat "backup-push+succeeded"
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
