#!/bin/sh
set -eu

project="damdam-walg-pitr-${GITHUB_RUN_ID:-local-$$}"
compose="docker compose --project-name $project --env-file compose.walg-test.env -f docker-compose.yml -f docker-compose.walg-test.yml"

cleanup() {
  $compose down --volumes --remove-orphans
}
trap cleanup EXIT INT TERM

sql() {
  $compose exec -T postgres psql -X -qAt \
    -U damdam_test -d damdam_test -v ON_ERROR_STOP=1 -c "$1"
}

start_postgres() {
  if ! $compose up -d --wait postgres; then
    echo "Postgres failed to become healthy; recovery/startup logs follow" >&2
    $compose logs postgres >&2
    return 1
  fi
}

wait_for_archive_count() {
  baseline="$1"
  limit_seconds="$2"
  started="$(date +%s)"
  while :; do
    current="$(sql 'SELECT archived_count FROM pg_stat_archiver')"
    if [ "$current" -gt "$baseline" ]; then
      ARCHIVE_ELAPSED_SECONDS=$(( $(date +%s) - started ))
      export ARCHIVE_ELAPSED_SECONDS
      return 0
    fi
    if [ $(( $(date +%s) - started )) -ge "$limit_seconds" ]; then
      echo "Timed out waiting for archived_count to exceed $baseline" >&2
      $compose logs postgres >&2
      return 1
    fi
    sleep 2
  done
}

echo "== Build the real Postgres + WAL-G image =="
$compose build postgres

echo "== Start Postgres with a local S3-compatible MinIO target =="
start_postgres

echo "== Prove the requested Postgres archive configuration is active =="
settings="$(sql "SELECT name || '=' || setting FROM pg_settings WHERE name IN ('archive_mode','archive_command','archive_timeout') ORDER BY name")"
printf '%s\n' "$settings"
printf '%s\n' "$settings" | grep -Fx 'archive_command=wal-g wal-push %p'
printf '%s\n' "$settings" | grep -Fx 'archive_mode=on'
printf '%s\n' "$settings" | grep -Fx 'archive_timeout=60'

echo "== Seed data and take a physical base backup =="
sql "CREATE TABLE pitr_proof (id integer PRIMARY KEY, value text NOT NULL); INSERT INTO pitr_proof VALUES (1, 'present-in-base-backup')"
echo "== Prove the scheduled companion performs backup-push and native retention =="
$compose up -d walg
started="$(date +%s)"
until $compose logs walg 2>&1 | grep -q 'WAL-G retention completed successfully'; do
  if [ $(( $(date +%s) - started )) -ge 30 ]; then
    echo "WAL-G companion did not complete its initial backup/retention cycle" >&2
    $compose logs walg >&2
    exit 1
  fi
  sleep 1
done
$compose logs walg
$compose stop walg
$compose run --rm --no-deps walg wal-g backup-list

echo "== Seed a balanced journal so the restore can be reconciled, not just counted =="
# A restore that returns rows is not the same as a restore that returns a
# consistent business state. These two rows are one double-entry transaction:
# if recovery ever landed inside a transaction rather than on a boundary, the
# recovered journal would not sum to zero and the books would be broken in a
# way a row count cannot see (US-42, chunk 26D).
sql "CREATE TABLE pitr_journal (id integer PRIMARY KEY, entry text NOT NULL, amount numeric(18,6) NOT NULL)"
sql "BEGIN; INSERT INTO pitr_journal VALUES (1, 'entry-a', 2500.000000), (2, 'entry-a', -2500.000000); COMMIT"

echo "== Prove archive_timeout pushes a low-traffic WAL segment =="
baseline="$(sql 'SELECT archived_count FROM pg_stat_archiver')"
sql "INSERT INTO pitr_proof VALUES (2, 'committed-after-base-and-recovered-from-wal')"
sql "BEGIN; INSERT INTO pitr_journal VALUES (3, 'entry-b', 700.000000), (4, 'entry-b', -700.000000); COMMIT"
recovery_target="$(sql "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')")"
wait_for_archive_count "$baseline" 90
echo "archive_timeout_seconds_observed=$ARCHIVE_ELAPSED_SECONDS"
test "$ARCHIVE_ELAPSED_SECONDS" -le 90

echo "== Archive a later transaction that the recovery target must exclude =="
sleep 1
baseline="$(sql 'SELECT archived_count FROM pg_stat_archiver')"
sql "BEGIN; INSERT INTO pitr_journal VALUES (5, 'entry-c', 900.000000), (6, 'entry-c', -900.000000); COMMIT"
sql "INSERT INTO pitr_proof VALUES (3, 'committed-after-recovery-target'); SELECT pg_switch_wal()"
wait_for_archive_count "$baseline" 30
$compose run --rm --no-deps walg wal-g wal-show

echo "== Simulate total Postgres volume loss =="
$compose stop postgres
$compose rm -f postgres walg
docker volume rm "${project}_postgres_data"

echo "== Restore latest base backup and replay WAL to $recovery_target =="
# Recovery time objective, measured rather than asserted: the clock starts when
# the data is gone and stops when the database is accepting queries again. A
# drill that proves correctness but never measures duration cannot tell anybody
# how long an outage would last (US-42, chunk 26D).
recovery_started="$(date +%s)"
$compose run --rm --no-deps walg walg-restore "$recovery_target"
start_postgres
RECOVERY_SECONDS=$(( $(date +%s) - recovery_started ))
echo "recovery_time_seconds=$RECOVERY_SECONDS"

echo "== Verify actual recovered data and point-in-time boundary =="
recovered="$(sql 'SELECT id || chr(61) || value FROM pitr_proof ORDER BY id')"
printf '%s\n' "$recovered"
printf '%s\n' "$recovered" | grep -Fx '1=present-in-base-backup'
printf '%s\n' "$recovered" | grep -Fx '2=committed-after-base-and-recovered-from-wal'
if printf '%s\n' "$recovered" | grep -q '^3='; then
  echo "Recovery incorrectly included a transaction after recovery_target_time" >&2
  exit 1
fi
test "$(sql 'SELECT pg_is_in_recovery()')" = "f"

echo "== Reconcile the recovered journal =="
# The books balance. If recovery had landed mid-transaction, one leg of a
# double entry would be present without its counterpart and this would not be
# zero -- which is the failure a row count cannot detect.
journal_sum="$(sql 'SELECT COALESCE(SUM(amount), 0)::numeric(18,6) FROM pitr_journal')"
echo "recovered_journal_sum=$journal_sum"
test "$journal_sum" = "0.000000"

# Every entry recovered has both its legs: no half-written transaction.
unbalanced="$(sql "SELECT COUNT(*) FROM (SELECT entry FROM pitr_journal GROUP BY entry HAVING SUM(amount) <> 0) AS broken")"
echo "unbalanced_entries=$unbalanced"
test "$unbalanced" = "0"

# The post-target transaction is absent in full, not in part.
post_target_legs="$(sql "SELECT COUNT(*) FROM pitr_journal WHERE entry = 'entry-c'")"
echo "post_target_legs_recovered=$post_target_legs"
test "$post_target_legs" = "0"

echo "PITR_PROOF=PASS base row present, post-backup WAL row recovered, post-target row absent"
echo "PITR_RECONCILIATION=PASS journal balances, no half-written transaction, post-target transaction excluded whole"
echo "PITR_RECOVERY_TIME_SECONDS=$RECOVERY_SECONDS"
