import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import { AuthResponse, OtpApiError, refreshSession } from '../api/authClient';
import { findActivePackageId, getMyPackages } from '../api/packagesClient';
import {
  BACKGROUND_PIN_THRESHOLD_MS,
  clearSession,
  isSessionExpired,
  loadSession,
  PersistedSession,
  saveSession,
  touchSession,
} from '../services/sessionStore';
import { clearPendingOrder } from '../services/pendingOrder';
import {
  clearAccountScopedState,
  hasPinStoredLocally,
} from '../utils/pinLocalStore';

/**
 * Whether this session has a PIN on this device to unlock against.
 *
 * A session persisted before US-29 carries no `userId`, so its PIN cannot be
 * attributed to an account; those fall through to full sign-in rather than
 * unlocking against whatever PIN happens to be on the device.
 */
async function hasLocalPin(session: PersistedSession): Promise<boolean> {
  if (!session.userId) {
    return false;
  }
  return hasPinStoredLocally(session.userId).catch(() => false);
}

export type SessionPhase = 'loading' | 'onboarding' | 'pin-gate' | 'authenticated';

export interface ActiveSession {
  /** US-30 AC-30.4: owner of this device's offline queues. */
  userId?: string;
  accessToken: string;
  refreshToken: string;
  /** Null for an account created through the email identity flow (US-29). */
  phoneNumber?: string | null;
  email?: string | null;
  departureDate: string | null;
  packageId?: string;
  locale: 'en' | 'fr';
}

export interface UseSessionGateResult {
  phase: SessionPhase;
  /** Populated once a session is known -- present during both 'pin-gate' (for
   * PinUnlockScreen's phoneNumber prop) and 'authenticated'. */
  session: ActiveSession | null;
  /** Called once OnboardingNavigator hands off a freshly authenticated session
   * (new signup, returning-pilgrim OTP login, or a fresh activation). */
  onOnboarded: (session: ActiveSession) => Promise<void>;
  /** Called by PinUnlockScreen: no argument on a routine correct-PIN unlock,
   * or a fresh AuthResponse when unlocked via OTP recovery instead. */
  onPinUnlocked: (recovered?: AuthResponse) => Promise<void>;
  /** Ends the current account session and clears device-local state owned by it. */
  onSignedOut: () => Promise<void>;
}

/**
 * The server-side access token TTL is 15 minutes
 * (apps/api/app/config.py's jwt_access_ttl_minutes). Refreshing well
 * before that boundary, on a timer, is what keeps check-in/SOS sends
 * from silently 401-ing (and retry-looping forever in their own
 * outbox, per checkInOutbox.ts/sosOutbox.ts) during a session that
 * stays continuously foregrounded for longer than 15 minutes without
 * ever backgrounding or cold-starting -- neither of which otherwise
 * triggers a refresh. Safety-critical enough (SOS delivery) that this
 * is not optional polish.
 */
const FOREGROUND_REFRESH_INTERVAL_MS = 12 * 60 * 1000;

function toActiveSession(persisted: PersistedSession): ActiveSession {
  return {
    userId: persisted.userId,
    accessToken: persisted.accessToken,
    refreshToken: persisted.refreshToken,
    phoneNumber: persisted.phoneNumber ?? null,
    email: persisted.email ?? null,
    departureDate: persisted.departureDate,
    packageId: persisted.packageId,
    locale: persisted.locale,
  };
}

/** AC-23.3: pure boundary check, exported for direct unit testing of the
 * background-duration threshold without going through AppState/React at all. */
export function shouldRequirePinAfterBackground(elapsedMs: number): boolean {
  return elapsedMs >= BACKGROUND_PIN_THRESHOLD_MS;
}

type RefreshOutcome = 'refreshed' | 'unchanged' | 'invalid';

/**
 * Best-effort refresh: a transient failure (network down, server
 * hiccup) must never strand or log out a user who otherwise still has
 * a valid session -- only a definitive invalid_refresh_token (the
 * session is truly dead server-side) is actionable. Shared between the
 * PIN-unlock resume path and the periodic in-foreground timer so both
 * apply the exact same success/transient/invalid handling.
 */
async function attemptRefresh(
  refreshToken: string,
): Promise<{ outcome: RefreshOutcome; session: PersistedSession | null }> {
  try {
    const refreshed = await refreshSession(refreshToken);
    const touched = await touchSession({
      accessToken: refreshed.access_token,
      refreshToken: refreshed.refresh_token,
    });
    return { outcome: 'refreshed', session: touched };
  } catch (error) {
    if (error instanceof OtpApiError && error.code === 'invalid_refresh_token') {
      return { outcome: 'invalid', session: null };
    }
    return { outcome: 'unchanged', session: null };
  }
}

/**
 * AC-23.1/AC-23.2/AC-23.3/AC-23.4 -- the session-persistence layer
 * frontend-mobile.md's PIN Unlock screen note (Screen 31) explicitly
 * left unbuilt: decides when a persisted session is still valid, when
 * it has aged past the 30-day inactivity ceiling, and when a
 * backgrounded app must re-clear the PIN gate before resuming.
 */
export function useSessionGate(): UseSessionGateResult {
  const [phase, setPhase] = useState<SessionPhase>('loading');
  const [session, setSession] = useState<ActiveSession | null>(null);
  const backgroundedAtRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const persisted = await loadSession();
      if (cancelled) {
        return;
      }
      if (!persisted) {
        setPhase('onboarding');
        return;
      }
      if (isSessionExpired(persisted.lastActiveAt)) {
        await clearSession();
        await clearAccountScopedState();
        await clearPendingOrder();
        if (cancelled) {
          return;
        }
        setPhase('onboarding');
        return;
      }
      setSession(toActiveSession(persisted));
      // A cold start is, from the user's perspective, exactly what
      // PinUnlockScreen's own doc comment calls "re-entering the PIN
      // after the app has been backgrounded" -- so it gates here.
      //
      // Only where there is a PIN to check, though (chunk 18). The PIN is a
      // *local* unlock gate (AC-23.5), never a network credential, and an
      // account created through the email identity flow never set one. Sending
      // it to a PIN screen would show a keypad no entry can satisfy and a
      // "forgot your PIN" path that needs a phone number the account does not
      // have.
      setPhase((await hasLocalPin(persisted)) ? 'pin-gate' : 'authenticated');
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const onOnboarded = useCallback(async (fresh: ActiveSession) => {
    await saveSession(fresh);
    setSession(fresh);
    setPhase('authenticated');
  }, []);

  const onSignedOut = useCallback(async () => {
    await clearSession();
    await clearAccountScopedState();
    await clearPendingOrder();
    setSession(null);
    setPhase('onboarding');
  }, []);

  const onPinUnlocked = useCallback(
    async (recovered?: AuthResponse) => {
      if (recovered) {
        // Re-fetch the account's current active package rather than
        // carrying forward whatever was previously persisted -- OTP
        // recovery can span enough time that the active package has
        // since changed (a new purchase, an expiry). Best-effort: a
        // failure here must not block the recovery unlock itself, so
        // it falls back to the previously known packageId rather than
        // stranding the user at the PIN gate over a balance-display
        // detail.
        const packageId = await getMyPackages(recovered.access_token)
          .then(findActivePackageId)
          .catch(() => session?.packageId);
        const next: ActiveSession = {
          userId: recovered.user.id,
          accessToken: recovered.access_token,
          refreshToken: recovered.refresh_token,
          phoneNumber: recovered.user.phone_number,
          departureDate: recovered.user.departure_date ?? null,
          packageId,
          locale: recovered.user.locale,
        };
        await saveSession(next);
        setSession(next);
        setPhase('authenticated');
        return;
      }

      const touched = await touchSession();
      if (!touched) {
        // Nothing persisted to unlock into -- fall back to onboarding
        // rather than entering 'authenticated' with a stale in-memory
        // session that no longer has durable backing.
        await clearAccountScopedState();
        await clearPendingOrder();
        setSession(null);
        setPhase('onboarding');
        return;
      }
      setSession(toActiveSession(touched));
      setPhase('authenticated');

      // Proactive refresh so a resumed session starts with a fresh
      // access token rather than one that may be near its 15-minute
      // server-side TTL.
      const result = await attemptRefresh(touched.refreshToken);
      if (result.outcome === 'invalid') {
        await clearSession();
        await clearAccountScopedState();
        await clearPendingOrder();
        setSession(null);
        setPhase('onboarding');
      } else if (result.session) {
        setSession(toActiveSession(result.session));
      }
    },
    [session],
  );

  useEffect(() => {
    const subscription = AppState.addEventListener(
      'change',
      (next: AppStateStatus) => {
        if (next === 'background' || next === 'inactive') {
          if (phase === 'authenticated' && backgroundedAtRef.current === null) {
            backgroundedAtRef.current = Date.now();
          }
          return;
        }
        if (next !== 'active') {
          return;
        }
        const backgroundedAt = backgroundedAtRef.current;
        backgroundedAtRef.current = null;
        if (backgroundedAt === null || phase !== 'authenticated') {
          return;
        }
        const elapsed = Date.now() - backgroundedAt;
        (async () => {
          const current = await loadSession();
          if (!current || isSessionExpired(current.lastActiveAt)) {
            await clearSession();
            await clearAccountScopedState();
            await clearPendingOrder();
            setSession(null);
            setPhase('onboarding');
            return;
          }
          if (
            shouldRequirePinAfterBackground(elapsed) &&
            (await hasLocalPin(current))
          ) {
            setPhase('pin-gate');
            return;
          }
          const touched = await touchSession();
          if (touched) {
            setSession(toActiveSession(touched));
          }
        })();
      },
    );
    return () => subscription.remove();
  }, [phase]);

  // AC-23.2 in spirit ("don't force re-login") extends to not letting the
  // access token silently go stale during a long continuously-foregrounded
  // session either -- see FOREGROUND_REFRESH_INTERVAL_MS. Only runs while
  // authenticated; reads the persisted refresh token fresh each tick
  // rather than closing over `session`, so it always uses the latest
  // token even if something else touched/refreshed it in between ticks.
  useEffect(() => {
    if (phase !== 'authenticated') {
      return undefined;
    }
    const timer = setInterval(() => {
      (async () => {
        const current = await loadSession();
        if (!current) {
          return;
        }
        if (isSessionExpired(current.lastActiveAt)) {
          await clearSession();
          await clearAccountScopedState();
          await clearPendingOrder();
          setSession(null);
          setPhase('onboarding');
          return;
        }
        const result = await attemptRefresh(current.refreshToken);
        if (result.outcome === 'invalid') {
          await clearSession();
          await clearAccountScopedState();
          await clearPendingOrder();
          setSession(null);
          setPhase('onboarding');
        } else if (result.session) {
          setSession(toActiveSession(result.session));
        }
      })();
    }, FOREGROUND_REFRESH_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [phase]);

  return { phase, session, onOnboarded, onPinUnlocked, onSignedOut };
}
