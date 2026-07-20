import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import { AuthResponse, OtpApiError, refreshSession } from '../api/authClient';
import {
  BACKGROUND_PIN_THRESHOLD_MS,
  clearSession,
  isSessionExpired,
  loadSession,
  PersistedSession,
  saveSession,
  touchSession,
} from '../services/sessionStore';

export type SessionPhase = 'loading' | 'onboarding' | 'pin-gate' | 'authenticated';

export interface ActiveSession {
  accessToken: string;
  refreshToken: string;
  phoneNumber: string;
  departureDate: string | null;
  packageId?: string;
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
}

function toActiveSession(persisted: PersistedSession): ActiveSession {
  return {
    accessToken: persisted.accessToken,
    refreshToken: persisted.refreshToken,
    phoneNumber: persisted.phoneNumber,
    departureDate: persisted.departureDate,
    packageId: persisted.packageId,
  };
}

/** AC-23.3: pure boundary check, exported for direct unit testing of the
 * background-duration threshold without going through AppState/React at all. */
export function shouldRequirePinAfterBackground(elapsedMs: number): boolean {
  return elapsedMs >= BACKGROUND_PIN_THRESHOLD_MS;
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
        if (cancelled) {
          return;
        }
        setPhase('onboarding');
        return;
      }
      setSession(toActiveSession(persisted));
      // A cold start is, from the user's perspective, exactly what
      // PinUnlockScreen's own doc comment calls "re-entering the PIN
      // after the app has been backgrounded" -- so it always gates here.
      setPhase('pin-gate');
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

  const onPinUnlocked = useCallback(
    async (recovered?: AuthResponse) => {
      if (recovered) {
        const next: ActiveSession = {
          accessToken: recovered.access_token,
          refreshToken: recovered.refresh_token,
          phoneNumber: recovered.user.phone_number,
          departureDate: recovered.user.departure_date ?? null,
          packageId: session?.packageId,
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
        setPhase('onboarding');
        return;
      }
      setSession(toActiveSession(touched));
      setPhase('authenticated');

      // Best-effort proactive refresh so a resumed session starts with a
      // fresh access token rather than one that may be near its 15-minute
      // server-side TTL. A transient failure here must never strand the
      // user who just proved possession of the device via PIN -- only a
      // definitive invalid_refresh_token (the session is truly dead
      // server-side) forces a drop back to onboarding.
      try {
        const refreshed = await refreshSession(touched.refreshToken);
        const withFreshTokens = await touchSession({
          accessToken: refreshed.access_token,
          refreshToken: refreshed.refresh_token,
        });
        if (withFreshTokens) {
          setSession(toActiveSession(withFreshTokens));
        }
      } catch (error) {
        if (error instanceof OtpApiError && error.code === 'invalid_refresh_token') {
          await clearSession();
          setSession(null);
          setPhase('onboarding');
        }
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
            setSession(null);
            setPhase('onboarding');
            return;
          }
          if (shouldRequirePinAfterBackground(elapsed)) {
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

  return { phase, session, onOnboarded, onPinUnlocked };
}
