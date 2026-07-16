import type {NetInfoState} from '@react-native-community/netinfo';
import {
  SOSSyncService,
  type SOSOutbox,
  type SOSOutboxItem,
} from './sosOutbox';

class PersistentSOSOutbox implements SOSOutbox {
  static rows: SOSOutboxItem[] = [];
  async initialize(): Promise<void> {}
  async enqueue(item: SOSOutboxItem): Promise<void> {
    if (!PersistentSOSOutbox.rows.some(row => row.clientGeneratedId === item.clientGeneratedId)) {
      PersistentSOSOutbox.rows.push(item);
    }
  }
  async pending(): Promise<SOSOutboxItem[]> { return [...PersistentSOSOutbox.rows]; }
  async remove(id: string): Promise<void> {
    PersistentSOSOutbox.rows = PersistentSOSOutbox.rows.filter(row => row.clientGeneratedId !== id);
  }
}

const online = {isConnected: true, isInternetReachable: true} as NetInfoState;
const offline = {isConnected: false, isInternetReachable: false} as NetInfoState;

beforeEach(() => { PersistentSOSOutbox.rows = []; jest.useFakeTimers(); });
afterEach(() => jest.useRealTimers());

it('AC-16.3: writes locally before network and keeps an honest queued state offline', async () => {
  const events: string[] = [];
  const outbox = new PersistentSOSOutbox();
  const enqueue = outbox.enqueue.bind(outbox);
  outbox.enqueue = async item => { events.push('local'); await enqueue(item); };
  const service = new SOSSyncService(outbox, async () => { events.push('network'); });
  const item = await service.capture({latitude: 21.422487, longitude: 39.826206}, new Date('2026-07-16T08:05:00Z'));
  expect(events).toEqual(['local']);
  expect(await service.isPending(item.clientGeneratedId)).toBe(true);
  await service.sync(offline);
  expect(events).toEqual(['local']);
});

it('AC-16.3 chaos: force-quit recreation preserves and syncs the identical UUID', async () => {
  const first = new SOSSyncService(new PersistentSOSOutbox(), jest.fn());
  const queued = await first.capture(undefined, new Date('2026-07-16T08:05:00Z'));
  const send = jest.fn().mockResolvedValue({id: 'server-alert', status: 'active'});
  const restarted = new SOSSyncService(new PersistentSOSOutbox(), send);
  await restarted.initialize();
  await restarted.sync(online);
  expect(send).toHaveBeenCalledWith(queued);
  expect(await new PersistentSOSOutbox().pending()).toEqual([]);
});

it('AC-16.7: rapid repeated completion reuses one in-flight alert ID', async () => {
  const service = new SOSSyncService(new PersistentSOSOutbox(), jest.fn());
  const [first, second, third] = await Promise.all([
    service.captureOnce(), service.captureOnce(), service.captureOnce(),
  ]);
  expect(new Set([first.clientGeneratedId, second.clientGeneratedId, third.clientGeneratedId]).size).toBe(1);
  expect(await new PersistentSOSOutbox().pending()).toHaveLength(1);
});

it('AC-16.3: retries every 10 seconds and immediately on connectivity restoration', async () => {
  const send = jest.fn().mockRejectedValueOnce(new Error('lost')).mockResolvedValue(undefined);
  const service = new SOSSyncService(new PersistentSOSOutbox(), send);
  await service.capture();
  const stop = service.start(() => online);
  await jest.advanceTimersByTimeAsync(10_000);
  expect(send).toHaveBeenCalledTimes(1);
  await service.connectivityChanged(online);
  expect(send).toHaveBeenCalledTimes(2);
  stop();
});

