/**
 * A real SQLite engine for Jest, shaped like `NitroSQLiteConnection`.
 *
 * Chunk 04's assignment requires mobile SQLite persistence to be tested with
 * its actual storage rather than an in-memory array that happens to behave
 * like a database. `react-native-nitro-sqlite` needs the native runtime, so
 * tests run the same SQL against sql.js (SQLite compiled to WebAssembly).
 *
 * This is a test helper. It is not shipped: nothing under `src/` imports it
 * outside a `*.test.ts` file.
 */

import type {NitroSQLiteConnection} from 'react-native-nitro-sqlite';

type SqlJsDatabase = {
  run(sql: string, params?: unknown[]): void;
  exec(sql: string, params?: unknown[]): {columns: string[]; values: unknown[][]}[];
  export(): Uint8Array;
  close(): void;
};

let engine: {Database: new (data?: Uint8Array) => SqlJsDatabase} | undefined;

export async function loadSqlEngine(): Promise<void> {
  if (engine) return;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const initSqlJs = require('sql.js') as (config?: object) => Promise<typeof engine>;
  engine = await initSqlJs();
}

/**
 * An open connection over a real SQLite database, exposing only the surface
 * the outboxes use. `snapshot()`/`restore()` model the app being killed and
 * relaunched against the same file on disk.
 */
export class TestSqliteConnection {
  private db: SqlJsDatabase;

  constructor(bytes?: Uint8Array) {
    if (!engine) throw new Error('call loadSqlEngine() first');
    this.db = new engine.Database(bytes);
  }

  async executeAsync<T>(sql: string, params: unknown[] = []): Promise<{rows: {_array: T[]}}> {
    const trimmed = sql.trim();
    const isRead = /^(SELECT|PRAGMA)/i.test(trimmed);
    if (!isRead) {
      this.db.run(trimmed, params);
      return {rows: {_array: []}};
    }
    const result = this.db.exec(trimmed, params);
    if (result.length === 0) return {rows: {_array: []}};
    const [{columns, values}] = result;
    const rows = values.map(row => {
      const record: Record<string, unknown> = {};
      columns.forEach((column, index) => {
        record[column] = row[index];
      });
      return record as T;
    });
    return {rows: {_array: rows}};
  }

  /** Bytes of the database file, as persisted on the device. */
  snapshot(): Uint8Array {
    return this.db.export();
  }

  close(): void {
    this.db.close();
  }

  asNitro(): NitroSQLiteConnection {
    return this as unknown as NitroSQLiteConnection;
  }
}

/** Simulates an app restart: same file, brand-new connection. */
export function reopen(connection: TestSqliteConnection): TestSqliteConnection {
  return new TestSqliteConnection(connection.snapshot());
}
