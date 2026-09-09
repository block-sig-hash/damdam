/**
 * US-30 / AC-30.4 — offline events must never be attributed to the next
 * signed-in account.
 *
 * This is the original review's finding 1. Strict TDD applies: these tests are
 * the safety-transition coverage required by `testing-qa.md` §14.13.1 while the
 * check-in and SOS queues are being retired, and they were written and
 * confirmed failing against the unfixed code before the fix existed.
 *
 * SQLite behaviour is exercised against a real engine (sql.js), not a stand-in
 * array, because the defect lives in what the *table* records and what the
 * *query* filters — an array double would happily pass a broken schema.
 */

import type {NetInfoState} from '@react-native-community/netinfo';

import {
  CheckInSyncService,
  NitroCheckInOutbox,
  type CheckInOutboxItem,
} from './checkInOutbox';
import {NitroSOSOutbox, SOSSyncService, type SOSOutboxItem} from './sosOutbox';
import {TestSqliteConnection, loadSqlEngine, reopen} from './testSqlite';

const ALICE = 'aaaaaaaa-0000-4000-8000-00000000000a';
const BOB = 'bbbbbbbb-0000-4000-8000-00000000000b';

const online = {isConnected: true, isInternetReachable: true} as NetInfoState;

beforeAll(loadSqlEngine);

/** An outbox bound to a real SQLite connection instead of the native module. */
function checkInOutboxOn(connection: TestSqliteConnection): NitroCheckInOutbox {
  const outbox = new NitroCheckInOutbox();
  outbox.useConnection(connection.asNitro());
  return outbox;
}

function sosOutboxOn(connection: TestSqliteConnection): NitroSOSOutbox {
  const outbox = new NitroSOSOutbox();
  outbox.useConnection(connection.asNitro());
  return outbox;
}

const item = (id: string, timestamp: string): CheckInOutboxItem & SOSOutboxItem => ({
  clientGeneratedId: id,
  timestamp,
});

describe('AC-30.4: queued rows are owned', () => {
  it('stores the owner alongside every queued check-in', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    const columns = await connection.executeAsync<{name: string}>(
      'PRAGMA table_info(checkin_outbox)',
    );
    expect(columns.rows._array.map(c => c.name)).toContain('owner_user_id');
  });

  it("never returns another account's queued check-ins", async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);
    await outbox.enqueue(item('b1', '2026-09-09T08:01:00.000Z'), BOB);

    expect((await outbox.pending(ALICE)).map(r => r.clientGeneratedId)).toEqual(['a1']);
    expect((await outbox.pending(BOB)).map(r => r.clientGeneratedId)).toEqual(['b1']);
  });

  it("never returns another account's queued SOS", async () => {
    const connection = new TestSqliteConnection();
    const outbox = sosOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);
    await outbox.enqueue(item('b1', '2026-09-09T08:01:00.000Z'), BOB);

    expect((await outbox.pending(BOB)).map(r => r.clientGeneratedId)).toEqual(['b1']);
  });

  it("cannot remove another account's row", async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    await outbox.remove('a1', BOB);

    expect(await outbox.pending(ALICE)).toHaveLength(1);
  });

  it('refuses to queue a row with no owner', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();

    await expect(
      outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ''),
    ).rejects.toThrow(/owner/i);
  });

  it('refuses a whitespace-only owner', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();

    await expect(
      outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), '   '),
    ).rejects.toThrow(/owner/i);
  });

  it('survives a process restart with ownership intact', async () => {
    const first = new TestSqliteConnection();
    const outbox = checkInOutboxOn(first);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    // Same file on disk, brand-new connection: the app was killed and relaunched.
    const second = reopen(first);
    const afterRestart = checkInOutboxOn(second);
    await afterRestart.initialize();

    expect(await afterRestart.pending(BOB)).toEqual([]);
    expect((await afterRestart.pending(ALICE)).map(r => r.clientGeneratedId)).toEqual(['a1']);
  });
});

describe('AC-30.4/AC-30.6: legacy rows are quarantined, never adopted', () => {
  async function seedLegacyDatabase(table: string): Promise<TestSqliteConnection> {
    const connection = new TestSqliteConnection();
    // Exactly the pre-chunk-04 schema: no owner column.
    await connection.executeAsync(
      `CREATE TABLE ${table} (
        client_generated_id TEXT PRIMARY KEY NOT NULL,
        timestamp TEXT NOT NULL,
        latitude REAL,
        longitude REAL
      )`,
    );
    await connection.executeAsync(
      `INSERT INTO ${table} (client_generated_id, timestamp, latitude, longitude)
       VALUES ('legacy-1', '2026-07-13T08:00:00.000Z', 21.4, 39.8)`,
    );
    return connection;
  }

  it('moves ownerless check-in rows to quarantine instead of assigning them', async () => {
    const connection = await seedLegacyDatabase('checkin_outbox');
    const outbox = checkInOutboxOn(connection);

    await outbox.initialize();

    // Not adopted by whoever signs in next -- by anyone.
    expect(await outbox.pending(ALICE)).toEqual([]);
    expect(await outbox.pending(BOB)).toEqual([]);
    expect(await outbox.quarantinedCount()).toBe(1);

    const quarantined = await connection.executeAsync<{client_generated_id: string}>(
      'SELECT client_generated_id FROM checkin_outbox_quarantine',
    );
    expect(quarantined.rows._array.map(r => r.client_generated_id)).toEqual(['legacy-1']);
  });

  it('moves ownerless SOS rows to quarantine instead of assigning them', async () => {
    const connection = await seedLegacyDatabase('sos_outbox');
    const outbox = sosOutboxOn(connection);

    await outbox.initialize();

    expect(await outbox.pending(ALICE)).toEqual([]);
    expect(await outbox.quarantinedCount()).toBe(1);
  });

  it('does not lose the quarantined data', async () => {
    const connection = await seedLegacyDatabase('checkin_outbox');
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();

    const rows = await connection.executeAsync<{timestamp: string; latitude: number}>(
      'SELECT timestamp, latitude FROM checkin_outbox_quarantine',
    );
    expect(rows.rows._array[0].timestamp).toBe('2026-07-13T08:00:00.000Z');
    expect(rows.rows._array[0].latitude).toBeCloseTo(21.4);
  });

  it('is idempotent across repeated initialization', async () => {
    const connection = await seedLegacyDatabase('checkin_outbox');
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.initialize();

    const reopened = checkInOutboxOn(reopen(connection));
    await reopened.initialize();

    expect(await reopened.quarantinedCount()).toBe(1);
  });
});

describe('AC-30.4: an account switch cannot dispatch the previous account\'s events', () => {
  function serviceFor(
    outbox: NitroCheckInOutbox,
    owner: string,
    currentOwner: () => string | undefined,
    send: (item: CheckInOutboxItem) => Promise<unknown>,
  ): CheckInSyncService {
    return new CheckInSyncService(outbox, send, () => undefined, () => undefined, {
      ownerUserId: owner,
      currentOwnerUserId: currentOwner,
    });
  }

  it('sends nothing after A signs out and B signs in', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    let signedIn: string | undefined = ALICE;
    const send = jest.fn(async () => ({}));
    const aliceService = serviceFor(outbox, ALICE, () => signedIn, send);

    signedIn = BOB; // A signs out, B signs in.
    const sent = await aliceService.sync(online);

    expect(sent).toBe(0);
    expect(send).not.toHaveBeenCalled();
    // A's row is preserved for A, not consumed or reassigned.
    expect(await outbox.pending(ALICE)).toHaveLength(1);
  });

  it("B's own sync never picks up A's rows", async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    const send = jest.fn(async () => ({}));
    const bobService = serviceFor(outbox, BOB, () => BOB, send);

    expect(await bobService.sync(online)).toBe(0);
    expect(send).not.toHaveBeenCalled();
  });

  it('discards a delayed callback that resolves after the account switched', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    let signedIn: string | undefined = ALICE;
    let release: (value: unknown) => void = () => undefined;
    const inFlight = new Promise(resolve => {
      release = resolve;
    });
    const synced = jest.fn();
    const service = new CheckInSyncService(
      outbox,
      async () => inFlight,
      () => undefined,
      synced,
      {ownerUserId: ALICE, currentOwnerUserId: () => signedIn},
    );

    const pending = service.sync(online);
    // The request is already in flight when the account changes underneath it.
    signedIn = BOB;
    release({});
    await pending;

    expect(synced).not.toHaveBeenCalled();
    // The row is NOT removed: it was never confirmed for its rightful owner.
    expect(await outbox.pending(ALICE)).toHaveLength(1);
  });

  it('still syncs normally while the same account stays signed in', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    const send = jest.fn(async () => ({}));
    const service = serviceFor(outbox, ALICE, () => ALICE, send);

    expect(await service.sync(online)).toBe(1);
    expect(send).toHaveBeenCalledTimes(1);
    expect(await outbox.pending(ALICE)).toEqual([]);
  });

  it('sends nothing when nobody is signed in', async () => {
    const connection = new TestSqliteConnection();
    const outbox = checkInOutboxOn(connection);
    await outbox.initialize();
    await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

    const send = jest.fn(async () => ({}));
    const service = serviceFor(outbox, ALICE, () => undefined, send);

    expect(await service.sync(online)).toBe(0);
    expect(send).not.toHaveBeenCalled();
  });

  it('stops its timer so a signed-out session cannot keep polling', async () => {
    jest.useFakeTimers();
    try {
      const connection = new TestSqliteConnection();
      const outbox = sosOutboxOn(connection);
      await outbox.initialize();
      await outbox.enqueue(item('a1', '2026-09-09T08:00:00.000Z'), ALICE);

      let signedIn: string | undefined = ALICE;
      const send = jest.fn(async () => ({}));
      const service = new SOSSyncService(
        outbox,
        send,
        () => undefined,
        () => undefined,
        {ownerUserId: ALICE, currentOwnerUserId: () => signedIn},
      );
      const stop = service.start(() => online);

      signedIn = undefined; // signed out
      stop();
      jest.advanceTimersByTime(60_000);

      expect(send).not.toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });
});
