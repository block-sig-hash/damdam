import type { NetInfoState } from '@react-native-community/netinfo';
import {
  CheckInSyncService,
  type CheckInOutbox,
  type CheckInOutboxItem,
} from './checkInOutbox';

/**
 * US-30 AC-30.4: the double records an owner per row, like the real table, so
 * these tests cannot pass against a queue that has lost account scoping.
 * Cross-account behaviour itself is covered in outboxAccountIsolation.test.ts
 * against a real SQLite engine.
 */
class PersistentTestOutbox implements CheckInOutbox {
  static rows: (CheckInOutboxItem & {ownerUserId: string})[] = [];

  async initialize(): Promise<void> {}
  async enqueue(item: CheckInOutboxItem, ownerUserId: string): Promise<void> {
    PersistentTestOutbox.rows.push({...item, ownerUserId});
  }
  async pending(ownerUserId: string): Promise<CheckInOutboxItem[]> {
    return PersistentTestOutbox.rows
      .filter(row => row.ownerUserId === ownerUserId)
      .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
      .map(({ownerUserId: _owner, ...item}) => item);
  }
  async remove(clientGeneratedId: string, ownerUserId: string): Promise<void> {
    PersistentTestOutbox.rows = PersistentTestOutbox.rows.filter(
      row =>
        !(row.clientGeneratedId === clientGeneratedId && row.ownerUserId === ownerUserId),
    );
  }
  async updateLocation(
    clientGeneratedId: string,
    location: {latitude: number; longitude: number},
    ownerUserId: string,
  ): Promise<void> {
    PersistentTestOutbox.rows = PersistentTestOutbox.rows.map(row =>
      row.clientGeneratedId === clientGeneratedId && row.ownerUserId === ownerUserId
        ? {...row, ...location}
        : row,
    );
  }
}

const OWNER = 'test-owner-0000-4000-8000-000000000001';
/** The signed-in account never changes in this file; see the isolation suite. */
const ownership = {ownerUserId: OWNER, currentOwnerUserId: () => OWNER};
const noop = () => undefined;

const online = {isConnected: true, isInternetReachable: true} as NetInfoState;
const offline = {isConnected: false, isInternetReachable: false} as NetInfoState;

beforeEach(() => {
  PersistentTestOutbox.rows = [];
  jest.useFakeTimers();
});

afterEach(() => jest.useRealTimers());

it('AC-15.1/15.2/15.4: writes the UUID, tap timestamp, and GPS before any network attempt', async () => {
  const events: string[] = [];
  const outbox = new PersistentTestOutbox();
  const enqueue = outbox.enqueue.bind(outbox);
  outbox.enqueue = async (item, ownerUserId) => {
    events.push('local-write');
    await enqueue(item, ownerUserId);
  };
  const send = jest.fn(async () => events.push('network'));
  const service = new CheckInSyncService(outbox, send, noop, noop, ownership);

  const item = await service.capture(
    {latitude: 21.422487, longitude: 39.826206},
    new Date('2026-07-13T08:05:00Z'),
  );

  expect(item.clientGeneratedId).toMatch(/^[0-9a-f-]{36}$/);
  expect(item.timestamp).toBe('2026-07-13T08:05:00.000Z');
  expect(item.latitude).toBe(21.422487);
  expect(events).toEqual(['local-write']);
  await service.sync(online);
  expect(events).toEqual(['local-write', 'network']);
});

it('AC-15.4: recreated service reads the same durable queue after an app restart', async () => {
  const firstProcess = new CheckInSyncService(new PersistentTestOutbox(), jest.fn(), noop, noop, ownership);
  const queued = await firstProcess.capture(undefined, new Date('2026-07-13T08:05:00Z'));

  const sendAfterRestart = jest.fn().mockResolvedValue(undefined);
  const restartedProcess = new CheckInSyncService(
    new PersistentTestOutbox(),
    sendAfterRestart,
    noop,
    noop,
    ownership,
  );
  await restartedProcess.initialize();
  await restartedProcess.sync(online);

  expect(sendAfterRestart).toHaveBeenCalledWith(queued);
  expect(await new PersistentTestOutbox().pending(OWNER)).toEqual([]);
});

it('AC-15.4: retries every 30 seconds and immediately when connectivity returns', async () => {
  const outbox = new PersistentTestOutbox();
  const send = jest.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(undefined);
  const service = new CheckInSyncService(outbox, send, noop, noop, ownership);
  await service.capture(undefined, new Date('2026-07-13T08:05:00Z'));

  await service.sync(offline);
  expect(send).not.toHaveBeenCalled();
  const stop = service.start(() => online);
  await jest.advanceTimersByTimeAsync(30_000);
  expect(send).toHaveBeenCalledTimes(1);
  expect(await outbox.pending(OWNER)).toHaveLength(1);

  await service.connectivityChanged(online);
  expect(send).toHaveBeenCalledTimes(2);
  expect(await outbox.pending(OWNER)).toEqual([]);
  stop();
});

it('AC-15.4: response loss retries the identical client_generated_id', async () => {
  const outbox = new PersistentTestOutbox();
  const ids: string[] = [];
  const send = jest.fn(async (item: CheckInOutboxItem) => {
    ids.push(item.clientGeneratedId);
    if (ids.length === 1) throw new Error('response lost');
  });
  const service = new CheckInSyncService(outbox, send, noop, noop, ownership);
  await service.capture(undefined, new Date('2026-07-13T08:05:00Z'));

  await service.sync(online);
  await service.sync(online);

  expect(ids).toHaveLength(2);
  expect(new Set(ids).size).toBe(1);
});

it('AC-15.2/15.7: connectivity cannot send a row while GPS enrichment is pending', async () => {
  const send = jest.fn().mockResolvedValue(undefined);
  const service = new CheckInSyncService(new PersistentTestOutbox(), send, noop, noop, ownership);
  const item = await service.capture(
    undefined,
    new Date('2026-07-13T08:05:00Z'),
    true,
  );

  await service.connectivityChanged(online);
  expect(send).not.toHaveBeenCalled();

  await service.enrichLocation(item.clientGeneratedId, {
    latitude: 21.422487,
    longitude: 39.826206,
  });
  service.releaseEnrichment(item.clientGeneratedId);
  await service.connectivityChanged(online);

  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({latitude: 21.422487, longitude: 39.826206}),
  );
});
