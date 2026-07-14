import * as Keychain from 'react-native-keychain';

/**
 * AC-02.4/AC-23.5: mirrors apps/api/app/auth/pin.py's PINService
 * constants exactly, for the same 5-attempt/30-minute lockout — but
 * enforced entirely on-device (AC-02.3/AC-23.3), since the server's
 * bcrypt pin_hash is never transmitted post-set (prd.md §5.1) and
 * can't be reused here.
 */
export const PIN_UNLOCK_ATTEMPT_LIMIT = 5;
export const PIN_UNLOCK_LOCKOUT_SECONDS = 30 * 60;

const SERVICE = 'com.damdam.pin-unlock';

export interface LocalPinState {
  pin: string;
  failedAttempts: number;
  lockedUntil: string | null;
}

async function readState(): Promise<LocalPinState | null> {
  const credentials = await Keychain.getGenericPassword({ service: SERVICE });
  if (!credentials) {
    return null;
  }
  try {
    return JSON.parse(credentials.password) as LocalPinState;
  } catch {
    return null;
  }
}

async function writeState(state: LocalPinState): Promise<void> {
  await Keychain.setGenericPassword('pin', JSON.stringify(state), {
    service: SERVICE,
    // Device-specific and unlock-gated: never migrates to a new device
    // (a new device has no local PIN and must use OTP recovery, per
    // AC-23.4), and is unreadable while the device itself is locked.
    accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

/** Called once, right after PIN Setup's POST /auth/pin/set succeeds. */
export async function savePinLocally(pin: string): Promise<void> {
  await writeState({ pin, failedAttempts: 0, lockedUntil: null });
}

export async function hasPinStoredLocally(): Promise<boolean> {
  return (await readState()) !== null;
}

export async function getLocalPinState(): Promise<LocalPinState | null> {
  return readState();
}

/**
 * AC-02.3/AC-23.3: compares against the on-device copy only — no
 * network call. Resets the failure counter on a match, mirroring the
 * backend's verify_pin success path.
 */
export async function verifyPinLocally(pin: string): Promise<boolean> {
  const state = await readState();
  if (!state || state.pin !== pin) {
    return false;
  }
  await writeState({ ...state, failedAttempts: 0, lockedUntil: null });
  return true;
}

/**
 * AC-02.4/AC-23.5: the 5th failure sets a 30-minute local lock deadline.
 * Returns the updated state so the caller can read the new deadline
 * directly rather than re-fetching.
 */
export async function recordFailedPinAttempt(): Promise<LocalPinState | null> {
  const state = await readState();
  if (!state) {
    return null;
  }
  const failedAttempts = state.failedAttempts + 1;
  const lockedUntil =
    failedAttempts >= PIN_UNLOCK_ATTEMPT_LIMIT
      ? new Date(Date.now() + PIN_UNLOCK_LOCKOUT_SECONDS * 1000).toISOString()
      : state.lockedUntil;
  const next: LocalPinState = { ...state, failedAttempts, lockedUntil };
  await writeState(next);
  return next;
}

/**
 * AC-02.4/AC-23.5: called after a successful OTP-based recovery, which
 * bypasses the local lock without changing the PIN itself — matching
 * the backend's clear_lock_after_otp, which never touches pin_hash.
 */
export async function clearLocalPinLock(): Promise<void> {
  const state = await readState();
  if (!state) {
    return;
  }
  await writeState({ ...state, failedAttempts: 0, lockedUntil: null });
}

export async function clearPinLocally(): Promise<void> {
  await Keychain.resetGenericPassword({ service: SERVICE });
}
