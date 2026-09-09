import type {NetInfoState} from '@react-native-community/netinfo';
import {
  SOSSyncService,
  type SOSOutbox,
  type SOSOutboxItem,
} from './sosOutbox';

/**
 * US-30 AC-30.4: the double records an owner per row, exactly like the real
 * table, so these tests cannot pass against a queue that has lost account
 * scoping. Cross-account behaviour is covered in
 * outboxAccountIsolation.test.ts against a real SQLite engine.
 */
class PersistentSOSOutbox implements SOSOutbox {
  static rows: (SOSOutboxItem & {ownerUserId: string})[] = [];
  async initialize(): Promise<void> {}
  async enqueue(item: SOSOutboxItem, ownerUserId: string): Promise<void> {
    if (!PersistentSOSOutbox.rows.some(row => row.clientGeneratedId === item.clientGeneratedId)) {
      PersistentSOSOutbox.rows.push({...item, ownerUserId});
    }
  }
  async pending(ownerUserId: string): Promise<SOSOutboxItem[]> {
    return PersistentSOSOutbox.rows
      .filter(row => row.ownerUserId === ownerUserId)
      .map(({ownerUserId: _owner, ...item}) => item);
  }
  async remove(id: string, ownerUserId: string): Promise<void> {
    PersistentSOSOutbox.rows = PersistentSOSOutbox.rows.filter(
      row => !(row.clientGeneratedId === id && row.ownerUserId === ownerUserId),
    );
  }
}

const OWNER = 'test-owner-0000-4000-8000-000000000001';
/** The signed-in account never changes in this file; see the isolation suite. */
const ownership = {ownerUserId: OWNER, currentOwnerUserId: () => OWNER};
const noop = () => undefined;

const online = {isConnected: true, isInternetReachable: true} as NetInfoState;
const offline = {isConnected: false, isInternetReachable: false} as NetInfoState;

beforeEach(() => { PersistentSOSOutbox.rows = []; jest.useFakeTimers(); });
afterEach(() => jest.useRealTimers());

it('AC-16.3: writes locally before network and keeps an honest queued state offline', async () => {
  const events: string[] = [];
  const outbox = new PersistentSOSOutbox();
  const enqueue = outbox.enqueue.bind(outbox);
  outbox.enqueue = async (item, ownerUserId) => {
    events.push('local');
    await enqueue(item, ownerUserId);
  };
  const service = new SOSSyncService(
    outbox,
    async () => { events.push('network'); },
    noop,
    noop,
    ownership,
  );
  const item = await service.capture({latitude: 21.422487, longitude: 39.826206}, new Date('2026-07-16T08:05:00Z'));
  expect(events).toEqual(['local']);
  expect(await service.isPending(item.clientGeneratedId)).toBe(true);
  await service.sync(offline);
  expect(events).toEqual(['local']);
});

it('AC-16.3 chaos: force-quit recreation preserves and syncs the identical UUID', async () => {
  const first = new SOSSyncService(new PersistentSOSOutbox(), jest.fn(), noop, noop, ownership);
  const queued = await first.capture(undefined, new Date('2026-07-16T08:05:00Z'));
  const send = jest.fn().mockResolvedValue({id: 'server-alert', status: 'active'});
  const restarted = new SOSSyncService(new PersistentSOSOutbox(), send, noop, noop, ownership);
  await restarted.initialize();
  await restarted.sync(online);
  expect(send).toHaveBeenCalledWith(queued);
  expect(await new PersistentSOSOutbox().pending(OWNER)).toEqual([]);
});

it('AC-16.7: rapid repeated completion reuses one in-flight alert ID', async () => {
  const service = new SOSSyncService(new PersistentSOSOutbox(), jest.fn(), noop, noop, ownership);
  const [first, second, third] = await Promise.all([
    service.captureOnce(), service.captureOnce(), service.captureOnce(),
  ]);
  expect(new Set([first.clientGeneratedId, second.clientGeneratedId, third.clientGeneratedId]).size).toBe(1);
  expect(await new PersistentSOSOutbox().pending(OWNER)).toHaveLength(1);
});

it('AC-16.3: retries every 10 seconds and immediately on connectivity restoration', async () => {
  const send = jest.fn().mockRejectedValueOnce(new Error('lost')).mockResolvedValue(undefined);
  const service = new SOSSyncService(new PersistentSOSOutbox(), send, noop, noop, ownership);
  await service.capture();
  const stop = service.start(() => online);
  await jest.advanceTimersByTimeAsync(10_000);
  expect(send).toHaveBeenCalledTimes(1);
  await service.connectivityChanged(online);
  expect(send).toHaveBeenCalledTimes(2);
  stop();
});

