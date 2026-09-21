import AsyncStorage from '@react-native-async-storage/async-storage';

/**
 * What this phone keeps for one account, and how it stops keeping it (US-38, chunk 21).
 *
 * Two requirements from the assignment meet in this file, and they pull in
 * opposite directions:
 *
 * 1. *Keep necessary installation guidance and timestamped usage accessible
 *    offline* — so data has to survive on disk.
 * 2. *Account-scoped cache clearing* — so when somebody signs out and a
 *    different person signs in on the same handset, none of it survives.
 *
 * The resolution is that **every key carries the account id**, and signing out
 * removes every key for that account. A single shared key would be the defect:
 * on a shared handset it shows one customer's receipts to another, and the API
 * scoping proven on the server does nothing about data already on the device.
 *
 * ## Why keys are enumerated by prefix rather than tracked in an index
 *
 * An index has to be written before the data it indexes and cleared after, and a
 * crash between those two writes leaves an orphan nobody deletes. `AsyncStorage`
 * can list its own keys, so the prefix *is* the index and cannot drift from what
 * is actually stored.
 *
 * ## What is deliberately not cached
 *
 * Anything secret. Activation material, grant tokens, provider credentials and
 * session tokens do not pass through here — `sessionStore` uses the Keychain for
 * exactly that reason, and `AsyncStorage` is unencrypted. What lives here is
 * material a customer could screenshot anyway: a receipt they have already
 * seen, installation steps, and a usage reading with the time it was taken.
 *
 * Every cached payload keeps `observedAt`, and screens are required to show it.
 * A balance rendered without its age is a number the customer believes is now.
 */

const PREFIX = 'damdam.account.v1';

export type CacheSlice = 'receipts' | 'usage' | 'installation' | 'support';

export interface CachedPayload<T> {
  /** When the server told us. Not when we wrote it down. */
  observedAt: string;
  value: T;
}

function keyFor(userId: string, slice: CacheSlice): string {
  return `${PREFIX}.${userId}.${slice}`;
}

/** True for any key belonging to this account, whatever slice it holds. */
function belongsTo(key: string, userId: string): boolean {
  return key.startsWith(`${PREFIX}.${userId}.`);
}

export async function writeSlice<T>(
  userId: string,
  slice: CacheSlice,
  value: T,
  observedAt: string,
): Promise<void> {
  const payload: CachedPayload<T> = { observedAt, value };
  await AsyncStorage.setItem(keyFor(userId, slice), JSON.stringify(payload));
}

/**
 * Read what we had, or `null`.
 *
 * Returns `null` rather than throwing on unreadable JSON. A cache is a
 * convenience; a corrupt one must degrade to "we have nothing saved" and let the
 * screen ask the network, never take the account area down with it.
 */
export async function readSlice<T>(
  userId: string,
  slice: CacheSlice,
): Promise<CachedPayload<T> | null> {
  try {
    const raw = await AsyncStorage.getItem(keyFor(userId, slice));
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as CachedPayload<T>;
    if (!parsed || typeof parsed.observedAt !== 'string') {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Forget everything this phone holds for one account.
 *
 * Called on sign-out and on account switch. It removes by prefix, so a slice
 * added later is cleared by this function without anybody remembering to come
 * back and add it — the bug this shape exists to prevent.
 */
export async function clearAccount(userId: string): Promise<number> {
  const keys = await AsyncStorage.getAllKeys();
  const mine = keys.filter(key => belongsTo(key, userId));
  if (mine.length > 0) {
    await AsyncStorage.multiRemove(mine);
  }
  return mine.length;
}

/**
 * Forget every account's cache on this device.
 *
 * For "sign out every device" performed here, and for a customer handing the
 * phone on. Deliberately separate from `clearAccount`: clearing more than was
 * asked for is its own kind of wrong, and the two callers are different.
 */
export async function clearAllAccounts(): Promise<number> {
  const keys = await AsyncStorage.getAllKeys();
  const mine = keys.filter(key => key.startsWith(`${PREFIX}.`));
  if (mine.length > 0) {
    await AsyncStorage.multiRemove(mine);
  }
  return mine.length;
}
