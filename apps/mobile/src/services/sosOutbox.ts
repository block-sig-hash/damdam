import type {NetInfoState} from '@react-native-community/netinfo';
import type {NitroSQLiteConnection} from 'react-native-nitro-sqlite';
import uuid from 'react-native-uuid';

export interface SOSLocation { latitude: number; longitude: number; }
export interface SOSOutboxItem {
  clientGeneratedId: string;
  timestamp: string;
  latitude?: number;
  longitude?: number;
}
export interface SOSOutbox {
  initialize(): Promise<void>;
  enqueue(item: SOSOutboxItem): Promise<void>;
  pending(): Promise<SOSOutboxItem[]>;
  remove(clientGeneratedId: string): Promise<void>;
  updateLocation?(clientGeneratedId: string, location: SOSLocation): Promise<void>;
}

type SOSRow = {
  client_generated_id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
};

export class NitroSOSOutbox implements SOSOutbox {
  private database?: NitroSQLiteConnection;

  async initialize(): Promise<void> {
    if (this.database) return;
    const {open} = require('react-native-nitro-sqlite') as typeof import('react-native-nitro-sqlite');
    this.database = open({name: 'damdam-safety.sqlite'});
    await this.database.executeAsync(
      `CREATE TABLE IF NOT EXISTS sos_outbox (
        client_generated_id TEXT PRIMARY KEY NOT NULL,
        timestamp TEXT NOT NULL,
        latitude REAL,
        longitude REAL
      )`,
    );
  }

  private async db(): Promise<NitroSQLiteConnection> {
    await this.initialize();
    if (!this.database) throw new Error('SOS outbox unavailable');
    return this.database;
  }

  async enqueue(item: SOSOutboxItem): Promise<void> {
    await (await this.db()).executeAsync(
      `INSERT OR IGNORE INTO sos_outbox
       (client_generated_id, timestamp, latitude, longitude) VALUES (?, ?, ?, ?)`,
      [item.clientGeneratedId, item.timestamp, item.latitude ?? null, item.longitude ?? null],
    );
  }

  async pending(): Promise<SOSOutboxItem[]> {
    const result = await (await this.db()).executeAsync<SOSRow>(
      `SELECT client_generated_id, timestamp, latitude, longitude
       FROM sos_outbox ORDER BY timestamp ASC`,
    );
    return result.rows._array.map(row => ({
      clientGeneratedId: row.client_generated_id,
      timestamp: row.timestamp,
      ...(row.latitude === null ? {} : {
        latitude: Number(row.latitude), longitude: Number(row.longitude),
      }),
    }));
  }

  async remove(clientGeneratedId: string): Promise<void> {
    await (await this.db()).executeAsync(
      'DELETE FROM sos_outbox WHERE client_generated_id = ?', [clientGeneratedId],
    );
  }

  async updateLocation(clientGeneratedId: string, location: SOSLocation): Promise<void> {
    await (await this.db()).executeAsync(
      'UPDATE sos_outbox SET latitude = ?, longitude = ? WHERE client_generated_id = ?',
      [location.latitude, location.longitude, clientGeneratedId],
    );
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
  ) {}

  async initialize(): Promise<SOSOutboxItem[]> {
    await this.outbox.initialize();
    const rows = await this.outbox.pending();
    this.onChanged(rows);
    return rows;
  }

  async capture(location?: SOSLocation, tappedAt = new Date(), holdForEnrichment = false): Promise<SOSOutboxItem> {
    await this.outbox.initialize();
    const item = {
      clientGeneratedId: String(uuid.v4()), timestamp: tappedAt.toISOString(), ...location,
    };
    await this.outbox.enqueue(item);
    if (holdForEnrichment) this.heldForEnrichment.add(item.clientGeneratedId);
    this.onChanged(await this.outbox.pending());
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
    await this.outbox.updateLocation?.(id, location);
  }

  releaseEnrichment(id: string): void { this.heldForEnrichment.delete(id); }

  async sync(state: NetInfoState): Promise<number> {
    if (!state.isConnected || state.isInternetReachable === false) return 0;
    if (this.syncing) return this.syncing;
    this.syncing = this.performSync();
    try { return await this.syncing; } finally { this.syncing = undefined; }
  }

  private async performSync(): Promise<number> {
    let sent = 0;
    for (const item of await this.outbox.pending()) {
      if (this.heldForEnrichment.has(item.clientGeneratedId)) continue;
      try {
        const response = await this.send(item);
        await this.outbox.remove(item.clientGeneratedId);
        this.onSynced(item, response);
        this.capturing = undefined;
        sent += 1;
      } catch { break; }
    }
    this.onChanged(await this.outbox.pending());
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
    return (await this.outbox.pending()).some(row => row.clientGeneratedId === id);
  }
}
