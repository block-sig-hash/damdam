import type {NetInfoState} from '@react-native-community/netinfo';
import type {NitroSQLiteConnection} from 'react-native-nitro-sqlite';
import uuid from 'react-native-uuid';

import {
  SAFETY_DATABASE,
  ensureOwnedOutboxTable,
  ownershipHolds,
  quarantinedRowCount,
  requireOwner,
  type OutboxOwnership,
} from './outboxOwnership';

export interface CheckInLocation {
  latitude: number;
  longitude: number;
}

export interface CheckInOutboxItem {
  clientGeneratedId: string;
  timestamp: string;
  latitude?: number;
  longitude?: number;
}

export interface CheckInOutbox {
  initialize(): Promise<void>;
  /** AC-30.4: a queued row always records the account it belongs to. */
  enqueue(item: CheckInOutboxItem, ownerUserId: string): Promise<void>;
  pending(ownerUserId: string): Promise<CheckInOutboxItem[]>;
  remove(clientGeneratedId: string, ownerUserId: string): Promise<void>;
  updateLocation?(
    clientGeneratedId: string,
    location: CheckInLocation,
    ownerUserId: string,
  ): Promise<void>;
  quarantinedCount?(): Promise<number>;
}

type OutboxRow = {
  client_generated_id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
};

export class NitroCheckInOutbox implements CheckInOutbox {
  private database?: NitroSQLiteConnection;
  private initialized = false;

  /** Test seam: run against a real SQLite connection without the native module. */
  useConnection(connection: NitroSQLiteConnection): void {
    this.database = connection;
    this.initialized = false;
  }

  async initialize(): Promise<void> {
    if (!this.database) {
      // Lazy loading keeps Jest and any pre-native bootstrap path from touching
      // the HybridObject before React Native has installed native modules.
      const {open} = require('react-native-nitro-sqlite') as typeof import('react-native-nitro-sqlite');
      this.database = open({name: SAFETY_DATABASE});
    }
    if (this.initialized) return;
    await ensureOwnedOutboxTable(this.database, 'checkin_outbox');
    this.initialized = true;
  }

  private async db(): Promise<NitroSQLiteConnection> {
    await this.initialize();
    if (!this.database) throw new Error('check-in outbox unavailable');
    return this.database;
  }

  async enqueue(item: CheckInOutboxItem, ownerUserId: string): Promise<void> {
    const owner = requireOwner(ownerUserId);
    const database = await this.db();
    await database.executeAsync(
      `INSERT OR IGNORE INTO checkin_outbox
       (client_generated_id, timestamp, latitude, longitude, owner_user_id)
       VALUES (?, ?, ?, ?, ?)`,
      [
        item.clientGeneratedId,
        item.timestamp,
        item.latitude ?? null,
        item.longitude ?? null,
        owner,
      ],
    );
  }

  async pending(ownerUserId: string): Promise<CheckInOutboxItem[]> {
    const owner = requireOwner(ownerUserId);
    const database = await this.db();
    const result = await database.executeAsync<OutboxRow>(
      `SELECT client_generated_id, timestamp, latitude, longitude
       FROM checkin_outbox WHERE owner_user_id = ? ORDER BY timestamp ASC`,
      [owner],
    );
    return result.rows._array.map(row => ({
      clientGeneratedId: row.client_generated_id,
      timestamp: row.timestamp,
      ...(row.latitude === null
        ? {}
        : {latitude: Number(row.latitude), longitude: Number(row.longitude)}),
    }));
  }

  async remove(clientGeneratedId: string, ownerUserId: string): Promise<void> {
    const owner = requireOwner(ownerUserId);
    const database = await this.db();
    await database.executeAsync(
      'DELETE FROM checkin_outbox WHERE client_generated_id = ? AND owner_user_id = ?',
      [clientGeneratedId, owner],
    );
  }

  async updateLocation(
    clientGeneratedId: string,
    location: CheckInLocation,
    ownerUserId: string,
  ): Promise<void> {
    const owner = requireOwner(ownerUserId);
    const database = await this.db();
    await database.executeAsync(
      `UPDATE checkin_outbox SET latitude = ?, longitude = ?
       WHERE client_generated_id = ? AND owner_user_id = ?`,
      [location.latitude, location.longitude, clientGeneratedId, owner],
    );
  }

  async quarantinedCount(): Promise<number> {
    return quarantinedRowCount(await this.db(), 'checkin_outbox');
  }
}

export class CheckInSyncService {
  private syncing?: Promise<number>;
  private readonly heldForEnrichment = new Set<string>();

  constructor(
    private readonly outbox: CheckInOutbox,
    private readonly send: (item: CheckInOutboxItem) => Promise<unknown>,
    private readonly onChanged: (pending: CheckInOutboxItem[]) => void = () => undefined,
    private readonly onSynced: (item: CheckInOutboxItem) => void = () => undefined,
    private readonly ownership: OutboxOwnership,
  ) {}

  private get owner(): string {
    return this.ownership.ownerUserId;
  }

  async initialize(): Promise<CheckInOutboxItem[]> {
    await this.outbox.initialize();
    const rows = await this.outbox.pending(this.owner);
    this.onChanged(rows);
    return rows;
  }

  async capture(
    location?: CheckInLocation,
    tappedAt = new Date(),
    holdForEnrichment = false,
  ): Promise<CheckInOutboxItem> {
    await this.outbox.initialize();
    const item: CheckInOutboxItem = {
      clientGeneratedId: String(uuid.v4()),
      timestamp: tappedAt.toISOString(),
      ...location,
    };
    if (holdForEnrichment) this.heldForEnrichment.add(item.clientGeneratedId);
    try {
      await this.outbox.enqueue(item, this.owner);
    } catch (error) {
      this.heldForEnrichment.delete(item.clientGeneratedId);
      throw error;
    }
    this.onChanged(await this.outbox.pending(this.owner));
    return item;
  }

  async enrichLocation(
    clientGeneratedId: string,
    location: CheckInLocation,
  ): Promise<void> {
    await this.outbox.updateLocation?.(clientGeneratedId, location, this.owner);
    this.onChanged(await this.outbox.pending(this.owner));
  }

  releaseEnrichment(clientGeneratedId: string): void {
    this.heldForEnrichment.delete(clientGeneratedId);
  }

  async sync(state: NetInfoState): Promise<number> {
    if (!state.isConnected || state.isInternetReachable === false) return 0;
    if (this.syncing) return this.syncing;
    this.syncing = this.performSync();
    try {
      return await this.syncing;
    } finally {
      this.syncing = undefined;
    }
  }

  private async performSync(): Promise<number> {
    // AC-30.4: the signed-in account must still be this queue's owner before a
    // single row is read, or A's events would be dispatched as B.
    if (!ownershipHolds(this.ownership)) return 0;

    let sent = 0;
    for (const item of await this.outbox.pending(this.owner)) {
      if (this.heldForEnrichment.has(item.clientGeneratedId)) continue;
      // Re-checked per item: a switch can land between two sends.
      if (!ownershipHolds(this.ownership)) break;
      try {
        await this.send(item);
        // Re-checked after the response: a delayed callback must not confirm or
        // consume a row once the account underneath it has changed.
        if (!ownershipHolds(this.ownership)) break;
        await this.outbox.remove(item.clientGeneratedId, this.owner);
        this.onSynced(item);
        sent += 1;
      } catch {
        break;
      }
    }
    if (ownershipHolds(this.ownership)) {
      this.onChanged(await this.outbox.pending(this.owner));
    }
    return sent;
  }

  start(networkState: () => NetInfoState): () => void {
    const timer = setInterval(() => {
      this.sync(networkState()).catch(() => undefined);
    }, 30_000);
    return () => clearInterval(timer);
  }

  async connectivityChanged(state: NetInfoState): Promise<number> {
    return this.sync(state);
  }

  async isPending(clientGeneratedId: string): Promise<boolean> {
    return (await this.outbox.pending(this.owner)).some(
      item => item.clientGeneratedId === clientGeneratedId,
    );
  }
}
