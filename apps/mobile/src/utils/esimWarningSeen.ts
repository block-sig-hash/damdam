import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY_PREFIX = 'esim-compatibility-warning-seen';

/**
 * Scoped per account (US-29). A device-wide flag meant that whoever dismissed
 * the warning first suppressed it for everyone who later signed in on the same
 * handset -- including someone with an incompatible device.
 */
function storageKey(userId: string): string {
  return `${STORAGE_KEY_PREFIX}:${userId}`;
}

/** AC-10.6: the warning modal fires once per device, not on every visit. */
export async function hasSeenEsimWarning(userId: string): Promise<boolean> {
  try {
    return (await AsyncStorage.getItem(storageKey(userId))) === 'true';
  } catch {
    // Local-storage failure defaults to "not seen" — worst case the
    // modal fires again, which is recoverable via Continue/Support,
    // not a data-loss or security concern.
    return false;
  }
}

export async function markEsimWarningSeen(userId: string): Promise<void> {
  try {
    await AsyncStorage.setItem(storageKey(userId), 'true');
  } catch {
    // Best-effort — a save failure just means the modal may fire
    // again next visit, not a blocking error for the user.
  }
}

/** Removes every account's dismissal flag when a session ends. */
export async function clearEsimWarningSeen(): Promise<void> {
  try {
    const keys = await AsyncStorage.getAllKeys();
    const ours = keys.filter(key => key.startsWith(STORAGE_KEY_PREFIX));
    if (ours.length > 0) {
      await AsyncStorage.multiRemove(ours);
    }
  } catch {
    // Best-effort: failing to clear a UX dismissal is not a security issue,
    // unlike the PIN, which is cleared through the Keychain above.
  }
}
