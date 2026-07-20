import * as Keychain from 'react-native-keychain';

/**
 * AC-23.1/AC-23.2: access/refresh tokens live in platform secure storage
 * (Android Keystore / iOS Keychain via react-native-keychain), never
 * AsyncStorage -- same mechanism and accessibility policy as
 * src/utils/pinLocalStore.ts, kept as a separate Keychain service since
 * a session and a locally-set PIN have independent lifecycles (e.g.
 * OTP-based PIN recovery replaces the session's tokens without ever
 * touching the PIN entry, per AC-23.4's "verified via PIN Unlock" path).
 */
export const SESSION_INACTIVITY_LIMIT_MS = 30 * 24 * 60 * 60 * 1000;

/** AC-23.3: PIN required once the app has been backgrounded this long. */
export const BACKGROUND_PIN_THRESHOLD_MS = 5 * 60 * 1000;

const SERVICE = 'com.damdam.session';

export interface PersistedSession {
  accessToken: string;
  refreshToken: string;
  phoneNumber: string;
  departureDate: string | null;
  packageId?: string;
  /** ISO timestamp of the last moment this session was known to be in active use. */
  lastActiveAt: string;
}

async function readState(): Promise<PersistedSession | null> {
  const credentials = await Keychain.getGenericPassword({ service: SERVICE });
  if (!credentials) {
    return null;
  }
  try {
    return JSON.parse(credentials.password) as PersistedSession;
  } catch {
    return null;
  }
}

async function writeState(session: PersistedSession): Promise<void> {
  await Keychain.setGenericPassword('session', JSON.stringify(session), {
    service: SERVICE,
    // Device-specific: a session never migrates to a new device (a new
    // device has no persisted session and must fully re-authenticate,
    // AC-23.4), and is unreadable while the device itself is locked.
    accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

/** Called on login/activation success and whenever the OTP-recovery path issues fresh tokens. */
export async function saveSession(
  session: Omit<PersistedSession, 'lastActiveAt'> & { lastActiveAt?: string },
): Promise<PersistedSession> {
  const next: PersistedSession = {
    ...session,
    lastActiveAt: session.lastActiveAt ?? new Date().toISOString(),
  };
  await writeState(next);
  return next;
}

export async function loadSession(): Promise<PersistedSession | null> {
  return readState();
}

export async function clearSession(): Promise<void> {
  await Keychain.resetGenericPassword({ service: SERVICE });
}

/**
 * Merges `patch` into the persisted session and stamps `lastActiveAt` to
 * now, in one read-modify-write. Used both for a routine "the app is
 * still in active use" touch (no patch) and for persisting freshly
 * issued tokens after a refresh (patch = {accessToken, refreshToken}).
 * Returns null if there is no session to touch (e.g. already cleared).
 */
export async function touchSession(
  patch: Partial<Omit<PersistedSession, 'lastActiveAt'>> = {},
): Promise<PersistedSession | null> {
  const current = await readState();
  if (!current) {
    return null;
  }
  const next: PersistedSession = {
    ...current,
    ...patch,
    lastActiveAt: new Date().toISOString(),
  };
  await writeState(next);
  return next;
}

/**
 * AC-23.2/AC-23.4: pure boundary check, exported so the 30-day cutoff is
 * directly unit-testable without touching Keychain. Exactly-30-days is
 * treated as expired (inclusive cutoff), matching the convention used
 * throughout the backend's own retention/session cutoffs.
 */
export function isSessionExpired(lastActiveAt: string, now: number = Date.now()): boolean {
  const lastActiveMs = new Date(lastActiveAt).getTime();
  return now - lastActiveMs >= SESSION_INACTIVITY_LIMIT_MS;
}
