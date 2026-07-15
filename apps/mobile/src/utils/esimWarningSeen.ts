import AsyncStorage from '@react-native-async-storage/async-storage';

const STORAGE_KEY = 'esim-compatibility-warning-seen';

/** AC-10.6: the warning modal fires once per device, not on every visit. */
export async function hasSeenEsimWarning(): Promise<boolean> {
  try {
    return (await AsyncStorage.getItem(STORAGE_KEY)) === 'true';
  } catch {
    // Local-storage failure defaults to "not seen" — worst case the
    // modal fires again, which is recoverable via Continue/Support,
    // not a data-loss or security concern.
    return false;
  }
}

export async function markEsimWarningSeen(): Promise<void> {
  try {
    await AsyncStorage.setItem(STORAGE_KEY, 'true');
  } catch {
    // Best-effort — a save failure just means the modal may fire
    // again next visit, not a blocking error for the user.
  }
}
