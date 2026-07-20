#!/bin/sh
set -eu

: "${PGDATA:=/var/lib/postgresql/data}"
recovery_target_time="${1:-}"
postgres_recovery_target_time=""

if [ -n "$recovery_target_time" ]; then
  case "$recovery_target_time" in
    ????-??-??T??:??:??Z | ????-??-??T??:??:??.??????Z) ;;
    *)
      echo "Recovery target must be an RFC3339 UTC timestamp, for example 2026-07-19T21:15:00Z" >&2
      exit 2
      ;;
  esac
  postgres_recovery_target_time="$(
    date -u --date="$recovery_target_time" '+%Y-%m-%d %H:%M:%S.%6N+00'
  )"
fi

mkdir -p "$PGDATA"
if [ -n "$(find "$PGDATA" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  echo "Refusing to restore into non-empty PGDATA: $PGDATA" >&2
  exit 2
fi

echo "Fetching the latest physical base backup into $PGDATA"
wal-g backup-fetch "$PGDATA" LATEST

{
  echo "restore_command = 'wal-g wal-fetch %f %p'"
  echo "recovery_target_timeline = 'latest'"
  echo "recovery_target_action = 'promote'"
  if [ -n "$postgres_recovery_target_time" ]; then
    printf "recovery_target_time = '%s'\n" "$postgres_recovery_target_time"
  fi
} >> "$PGDATA/postgresql.auto.conf"
touch "$PGDATA/recovery.signal"

echo "Restore prepared. Start Postgres to replay archived WAL${recovery_target_time:+ through $recovery_target_time}."
