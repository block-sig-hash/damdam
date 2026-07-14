import { useCallback, useEffect, useRef, useState } from 'react';
import { AuthResponse } from '../../api/authClient';
import { useCountdownSeconds } from '../../hooks/useCountdownSeconds';
import {
  clearLocalPinLock,
  getLocalPinState,
  PIN_UNLOCK_ATTEMPT_LIMIT,
  recordFailedPinAttempt,
  verifyPinLocally,
} from '../../utils/pinLocalStore';

export const PIN_LENGTH = 4;

export type PinUnlockStage = 'checking' | 'entry' | 'locked' | 'no-local-pin';

interface UsePinUnlockArgs {
  /** Called with no argument on a routine local-PIN match; called with
   * the fresh AuthResponse when unlocked via OTP recovery instead. */
  onUnlocked: (recovered?: AuthResponse) => void;
}

export interface UsePinUnlockResult {
  stage: PinUnlockStage;
  value: string;
  setValue: (value: string) => void;
  errorMessage: string | null;
  lockoutSecondsRemaining: number;
  submit: () => Promise<void>;
  isRecovering: boolean;
  startRecovery: () => void;
  cancelRecovery: () => void;
  handleRecovered: (result: AuthResponse) => Promise<void>;
}

function secondsUntil(isoDate: string): number {
  return Math.max(0, Math.ceil((new Date(isoDate).getTime() - Date.now()) / 1000));
}

/**
 * US-02/US-23 — the two ACs PIN Setup (PR #43) explicitly deferred:
 * AC-02.3/AC-23.3 (local-only validation, no network call) and
 * AC-02.4/AC-23.5 (5-attempt local lockout, immediate OTP recovery).
 * Screen 31 of docs/frontend-mobile.md §8.1.
 */
export function usePinUnlock({ onUnlocked }: UsePinUnlockArgs): UsePinUnlockResult {
  const [stage, setStage] = useState<PinUnlockStage>('checking');
  const [value, setValueState] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lockoutTotalSeconds, setLockoutTotalSeconds] = useState(0);
  const [isRecovering, setIsRecovering] = useState(false);

  const lockoutSecondsRemaining = useCountdownSeconds(lockoutTotalSeconds);

  // Same latch useOtpVerification/useReturningPilgrimLogin use:
  // useCountdownSeconds' `remaining` state lags lockoutTotalSeconds by
  // one render, so a naive check would "expire" a lock that hasn't
  // started counting down yet.
  const hasObservedLockoutCountdown = useRef(false);
  useEffect(() => {
    if (stage !== 'locked') {
      return;
    }
    if (lockoutSecondsRemaining > 0) {
      hasObservedLockoutCountdown.current = true;
      return;
    }
    if (hasObservedLockoutCountdown.current) {
      hasObservedLockoutCountdown.current = false;
      setStage('entry');
      setErrorMessage(null);
      setLockoutTotalSeconds(0);
    }
  }, [stage, lockoutSecondsRemaining]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const state = await getLocalPinState();
      if (cancelled) {
        return;
      }
      if (!state) {
        setStage('no-local-pin');
        return;
      }
      const remaining = state.lockedUntil ? secondsUntil(state.lockedUntil) : 0;
      if (remaining > 0) {
        setLockoutTotalSeconds(remaining);
        setStage('locked');
        return;
      }
      setStage('entry');
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setValue = useCallback((next: string) => {
    setErrorMessage(null);
    setValueState(next.replace(/\D/g, '').slice(0, PIN_LENGTH));
  }, []);

  const submit = useCallback(async () => {
    if (value.length !== PIN_LENGTH || stage !== 'entry') {
      return;
    }
    const matched = await verifyPinLocally(value);
    setValueState('');
    if (matched) {
      onUnlocked();
      return;
    }
    const updated = await recordFailedPinAttempt();
    if (updated?.lockedUntil) {
      setLockoutTotalSeconds(secondsUntil(updated.lockedUntil));
      setStage('locked');
      setErrorMessage('Too many attempts. Verify via OTP or wait for the lock to clear.');
      return;
    }
    const remaining = PIN_UNLOCK_ATTEMPT_LIMIT - (updated?.failedAttempts ?? 0);
    setErrorMessage(`Incorrect PIN. ${remaining} attempt${remaining === 1 ? '' : 's'} left.`);
  }, [value, stage, onUnlocked]);

  const startRecovery = useCallback(() => {
    setErrorMessage(null);
    setIsRecovering(true);
  }, []);

  const cancelRecovery = useCallback(() => {
    setIsRecovering(false);
  }, []);

  const handleRecovered = useCallback(
    async (result: AuthResponse) => {
      await clearLocalPinLock();
      setIsRecovering(false);
      onUnlocked(result);
    },
    [onUnlocked],
  );

  return {
    stage,
    value,
    setValue,
    errorMessage,
    lockoutSecondsRemaining,
    submit,
    isRecovering,
    startRecovery,
    cancelRecovery,
    handleRecovered,
  };
}
