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

export interface SOSLocation { latitude: number; longitude: number; }
export interface SOSOutboxItem {
  clientGeneratedId: string;
  timestamp: string;
  latitude?: number;
  longitude?: number;
}
export interface SOSOutbox {
  initialize(): Promise<void>;
  /** AC-30.4: a queued row always records the account it belongs to. */
  enqueue(item: SOSOutboxItem, ownerUserId: string): Promise<void>;
  pending(ownerUserId: string): Promise<SOSOutboxItem[]>;
  remove(clientGeneratedId: string, ownerUserId: string): Promise<void>;
  updateLocation?(
    clientGeneratedId: string,
    location: SOSLocation,
    ownerUserId: string,
  ): Promise<void>;
  quarantinedCount?(): Promise<number>;
}

type SOSRow = {
  client_generated_id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
};

export class NitroSOSOutbox implements SOSOutbox {
  private database?: NitroSQLiteConnection;
  private initialized = false;

  /** Test seam: run against a real SQLite connection without the native module. */
  useConnection(connection: NitroSQLiteConnection): void {
    this.database = connection;
    this.initialized = false;
  }

  async initialize(): Promise<void> {
    if (!this.database) {
      const {open} = require('react-native-nitro-sqlite') as typeof import('react-native-nitro-sqlite');
      this.database = open({name: SAFETY_DATABASE});
    }
    if (this.initialized) return;
    await ensureOwnedOutboxTable(this.database, 'sos_outbox');
    this.initialized = true;
  }

  private async db(): Promise<NitroSQLiteConnection> {
    await this.initialize();
    if (!this.database) throw new Error('SOS outbox unavailable');
    return this.database;
  }

  async enqueue(item: SOSOutboxItem, ownerUserId: string): Promise<void> {
    const owner = requireOwner(ownerUserId);
    await (await this.db()).executeAsync(
      `INSERT OR IGNORE INTO sos_outbox
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

  async pending(ownerUserId: string): Promise<SOSOutboxItem[]> {
    const owner = requireOwner(ownerUserId);
    const result = await (await this.db()).executeAsync<SOSRow>(
      `SELECT client_generated_id, timestamp, latitude, longitude
       FROM sos_outbox WHERE owner_user_id = ? ORDER BY timestamp ASC`,
      [owner],
    );
    return result.rows._array.map(row => ({
      clientGeneratedId: row.client_generated_id,
      timestamp: row.timestamp,
      ...(row.latitude === null ? {} : {
        latitude: Number(row.latitude), longitude: Number(row.longitude),
      }),
    }));
  }

  async remove(clientGeneratedId: string, ownerUserId: string): Promise<void> {
    const owner = requireOwner(ownerUserId);
    await (await this.db()).executeAsync(
      'DELETE FROM sos_outbox WHERE client_generated_id = ? AND owner_user_id = ?',
      [clientGeneratedId, owner],
    );
  }

  async updateLocation(
    clientGeneratedId: string,
    location: SOSLocation,
    ownerUserId: string,
  ): Promise<void> {
    const owner = requireOwner(ownerUserId);
    await (await this.db()).executeAsync(
      `UPDATE sos_outbox SET latitude = ?, longitude = ?
       WHERE client_generated_id = ? AND owner_user_id = ?`,
      [location.latitude, location.longitude, clientGeneratedId, owner],
    );
  }

  async quarantinedCount(): Promise<number> {
    return quarantinedRowCount(await this.db(), 'sos_outbox');
  }
}

export class SOSSyncService {
  private syncing?: Promise<number>;
  private capturing?: Promise<SOSOutboxItem>;
  private readonly heldForEnrichment = new Set<string>();

  constructor(
    private readonly outbox: SOSOutbox,
    private readonly send: (item: SOSOutboxItem) => Promise<unknown>,
    private readonly onChanged: (rows: SOSOutboxItem[]) => void = () => undefined,
    private readonly onSynced: (item: SOSOutboxItem, response: unknown) => void = () => undefined,
    private readonly ownership: OutboxOwnership,
  ) {}

  private get owner(): string {
    return this.ownership.ownerUserId;
  }

  async initialize(): Promise<SOSOutboxItem[]> {
    await this.outbox.initialize();
    const rows = await this.outbox.pending(this.owner);
    this.onChanged(rows);
    return rows;
  }

  async capture(location?: SOSLocation, tappedAt = new Date(), holdForEnrichment = false): Promise<SOSOutboxItem> {
    await this.outbox.initialize();
    const item = {
      clientGeneratedId: String(uuid.v4()), timestamp: tappedAt.toISOString(), ...location,
    };
    await this.outbox.enqueue(item, this.owner);
    if (holdForEnrichment) this.heldForEnrichment.add(item.clientGeneratedId);
    this.onChanged(await this.outbox.pending(this.owner));
    return item;
  }

  captureOnce(location?: SOSLocation, tappedAt = new Date(), holdForEnrichment = false): Promise<SOSOutboxItem> {
    if (!this.capturing) {
      this.capturing = (async () => {
        const existing = (await this.initialize())[0];
        return existing ?? this.capture(location, tappedAt, holdForEnrichment);
      })();
    }
    return this.capturing;
  }

  async enrichLocation(id: string, location: SOSLocation): Promise<void> {
    await this.outbox.updateLocation?.(id, location, this.owner);
  }

  releaseEnrichment(id: string): void { this.heldForEnrichment.delete(id); }

  async sync(state: NetInfoState): Promise<number> {
    if (!state.isConnected || state.isInternetReachable === false) return 0;
    if (this.syncing) return this.syncing;
    this.syncing = this.performSync();
    try { return await this.syncing; } finally { this.syncing = undefined; }
  }

  private async performSync(): Promise<number> {
    // AC-30.4: never read, let alone dispatch, another account's queued alerts.
    if (!ownershipHolds(this.ownership)) return 0;

    let sent = 0;
    for (const item of await this.outbox.pending(this.owner)) {
      if (this.heldForEnrichment.has(item.clientGeneratedId)) continue;
      if (!ownershipHolds(this.ownership)) break;
      try {
        const response = await this.send(item);
        // A delayed callback must not confirm an alert for an account that is
        // no longer signed in.
        if (!ownershipHolds(this.ownership)) break;
        await this.outbox.remove(item.clientGeneratedId, this.owner);
        this.onSynced(item, response);
        this.capturing = undefined;
        sent += 1;
      } catch { break; }
    }
    if (ownershipHolds(this.ownership)) {
      this.onChanged(await this.outbox.pending(this.owner));
    }
    return sent;
  }

  start(networkState: () => NetInfoState): () => void {
    const timer = setInterval(() => {
      this.sync(networkState()).catch(() => undefined);
    }, 10_000);
    return () => clearInterval(timer);
  }

  connectivityChanged(state: NetInfoState): Promise<number> { return this.sync(state); }
  async isPending(id: string): Promise<boolean> {
    return (await this.outbox.pending(this.owner)).some(row => row.clientGeneratedId === id);
  }
}
