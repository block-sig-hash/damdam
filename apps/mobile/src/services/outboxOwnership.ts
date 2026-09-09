/**
 * Account ownership for the offline safety queues (US-30, AC-30.4).
 *
 * The original review found that offline events could sync as the wrong
 * signed-in account: both queues lived in one device-wide SQLite file with no
 * owner column, so `pending()` returned every queued row and the sync loop sent
 * them with whichever token happened to be current.
 *
 * These helpers are shared by the check-in and SOS outboxes so the rule is
 * written once. They stay in force for as long as any transition path survives
 * retirement -- an event that cannot be attributed to a trustworthy owner is
 * never sent and never adopted.
 */

import type {NitroSQLiteConnection} from 'react-native-nitro-sqlite';

/** Both queues share one device database file. */
export const SAFETY_DATABASE = 'damdam-safety.sqlite';

export class OutboxOwnerError extends Error {}

/**
 * Who a sync service belongs to, and who is signed in right now.
 *
 * `currentOwnerUserId` is deliberately a function rather than a value: it is
 * resolved again immediately before each send *and* after each send resolves,
 * so an account switch mid-flight is caught rather than raced.
 */
export interface OutboxOwnership {
  readonly ownerUserId: string;
  currentOwnerUserId(): string | undefined;
}

export function requireOwner(ownerUserId: string): string {
  if (!ownerUserId.trim()) {
    throw new OutboxOwnerError(
      'refusing to queue an offline event with no owner: an unowned row cannot ' +
        'be attributed to an account later without risking the wrong one',
    );
  }
  return ownerUserId;
}

/** True only when the signed-in account is still the one this queue belongs to. */
export function ownershipHolds(ownership: OutboxOwnership): boolean {
  const current = ownership.currentOwnerUserId();
  return current !== undefined && current === ownership.ownerUserId;
}

type ColumnRow = {name: string};

/**
 * Create the owned table, and quarantine any rows left by a build that did not
 * record an owner.
 *
 * Those legacy rows are the actual defect: there is no trustworthy way to say
 * whose they are. They are moved to `<table>_quarantine` and kept -- not
 * deleted, because they are a user's data, and above all not assigned to
 * whoever signs in next.
 */
export async function ensureOwnedOutboxTable(
  database: NitroSQLiteConnection,
  table: string,
): Promise<void> {
  await database.executeAsync(
    `CREATE TABLE IF NOT EXISTS ${table} (
      client_generated_id TEXT PRIMARY KEY NOT NULL,
      timestamp TEXT NOT NULL,
      latitude REAL,
      longitude REAL,
      owner_user_id TEXT
    )`,
  );

  const columns = await database.executeAsync<ColumnRow>(`PRAGMA table_info(${table})`);
  const hasOwner = columns.rows._array.some(column => column.name === 'owner_user_id');

  if (!hasOwner) {
    // A pre-US-30 database. Add the column so the shapes match, then quarantine
    // every existing row -- each one predates ownership and cannot be claimed.
    await database.executeAsync(`ALTER TABLE ${table} ADD COLUMN owner_user_id TEXT`);
  }

  await database.executeAsync(
    `CREATE TABLE IF NOT EXISTS ${table}_quarantine (
      client_generated_id TEXT PRIMARY KEY NOT NULL,
      timestamp TEXT NOT NULL,
      latitude REAL,
      longitude REAL,
      quarantined_at TEXT NOT NULL,
      reason TEXT NOT NULL
    )`,
  );

  // Rows with no owner are quarantined on every initialize, not just the first:
  // an interrupted migration must converge, and a downgrade-then-upgrade cycle
  // can reintroduce ownerless rows.
  await database.executeAsync(
    `INSERT OR IGNORE INTO ${table}_quarantine
       (client_generated_id, timestamp, latitude, longitude, quarantined_at, reason)
     SELECT client_generated_id, timestamp, latitude, longitude,
            strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), 'no trustworthy owner (US-30 AC-30.4)'
     FROM ${table}
     WHERE owner_user_id IS NULL OR owner_user_id = ''`,
  );
  await database.executeAsync(
    `DELETE FROM ${table} WHERE owner_user_id IS NULL OR owner_user_id = ''`,
  );
}

export async function quarantinedRowCount(
  database: NitroSQLiteConnection,
  table: string,
): Promise<number> {
  const result = await database.executeAsync<{count: number}>(
    `SELECT COUNT(*) AS count FROM ${table}_quarantine`,
  );
  return Number(result.rows._array[0]?.count ?? 0);
}
