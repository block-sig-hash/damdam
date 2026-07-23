import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AuthResponse,
  OtpApiError,
  Platform,
  requestPinRecovery,
  verifyPinRecovery,
} from '../../api/authClient';
import {i18n} from '../../i18n';
import {normalizeLocale} from '../../i18n/locale';
import { useCountdownSeconds } from '../../hooks/useCountdownSeconds';
import { useElapsedSeconds } from '../../hooks/useElapsedSeconds';

const MANUAL_RESEND_THRESHOLD_SECONDS = 30;
const OTP_CODE_LENGTH = 6;

export type ReturningPilgrimLoginStatus = 'sending' | 'awaiting_code' | 'verifying' | 'locked';

interface UseReturningPilgrimLoginArgs {
  phoneNumber: string;
  platform: Platform;
  onVerified: (result: AuthResponse) => void;
}

export interface UseReturningPilgrimLoginResult {
  code: string;
  setCode: (value: string) => void;
  status: ReturningPilgrimLoginStatus;
  errorMessage: string | null;
  canResend: boolean;
  secondsUntilResend: number;
  lockoutSecondsRemaining: number;
  isResending: boolean;
  resend: () => Promise<void>;
  submit: () => Promise<void>;
}

/**
 * AC-01.7 / AC-07.5 / AC-23.4 — "full re-authentication" for a phone
 * number that already has an account and no valid local session.
 * There's no phone+PIN login endpoint (PIN is local-only, AC-23.5),
 * so this reuses US-02's OTP-based recovery pair exactly as already
 * built: unlike useOtpVerification (whose caller — Phone Entry — has
 * already sent the code before this screen mounts), this hook sends
 * the recovery code itself on mount, since nothing upstream has.
 */
export function useReturningPilgrimLogin({
  phoneNumber,
  platform,
  onVerified,
}: UseReturningPilgrimLoginArgs): UseReturningPilgrimLoginResult {
  const [sentAt, setSentAt] = useState(() => Date.now());
  const [code, setCodeState] = useState('');
  const [status, setStatus] = useState<ReturningPilgrimLoginStatus>('sending');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lockoutTotalSeconds, setLockoutTotalSeconds] = useState(0);
  const [resendBlockedTotalSeconds, setResendBlockedTotalSeconds] = useState(0);
  const [isResending, setIsResending] = useState(false);

  const secondsSinceSend = useElapsedSeconds(sentAt);
  const lockoutSecondsRemaining = useCountdownSeconds(lockoutTotalSeconds);
  const resendBlockedSecondsRemaining = useCountdownSeconds(resendBlockedTotalSeconds);

  // See useOtpVerification's identical latch for why this is needed:
  // useCountdownSeconds' `remaining` state lags `lockoutTotalSeconds`
  // by one render.
  const hasObservedLockoutCountdown = useRef(false);

  useEffect(() => {
    if (status !== 'locked') {
      return;
    }
    if (lockoutSecondsRemaining > 0) {
      hasObservedLockoutCountdown.current = true;
      return;
    }
    if (hasObservedLockoutCountdown.current) {
      hasObservedLockoutCountdown.current = false;
      setStatus('awaiting_code');
      setErrorMessage(null);
      setLockoutTotalSeconds(0);
    }
  }, [status, lockoutSecondsRemaining]);

  const sendCode = useCallback(async () => {
    setErrorMessage(null);
    try {
      await requestPinRecovery(phoneNumber, normalizeLocale(i18n.language));
      setSentAt(Date.now());
      setCodeState('');
      setStatus('awaiting_code');
    } catch (err) {
      setStatus('awaiting_code');
      if (err instanceof OtpApiError && err.code === 'rate_limited') {
        setResendBlockedTotalSeconds(err.retryAfter ?? MANUAL_RESEND_THRESHOLD_SECONDS);
        setErrorMessage('Please wait before requesting another code.');
      } else if (err instanceof OtpApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Something went wrong. Please try again.');
      }
    }
  }, [phoneNumber]);

  const hasSentInitialRequest = useRef(false);
  useEffect(() => {
    if (hasSentInitialRequest.current) {
      return;
    }
    hasSentInitialRequest.current = true;
    sendCode();
    // Auto-sends exactly once per screen mount; sendCode is stable
    // for a fixed phoneNumber.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setCode = useCallback((value: string) => {
    setErrorMessage(null);
    setCodeState(value.replace(/\D/g, '').slice(0, OTP_CODE_LENGTH));
  }, []);

  const submit = useCallback(async () => {
    if (code.length !== OTP_CODE_LENGTH || status === 'locked' || status === 'verifying') {
      return;
    }
    setStatus('verifying');
    setErrorMessage(null);
    try {
      const result = await verifyPinRecovery(
        phoneNumber,
        code,
        platform,
        normalizeLocale(i18n.language),
      );
      onVerified(result);
    } catch (err) {
      if (err instanceof OtpApiError && err.code === 'locked') {
        setStatus('locked');
        setLockoutTotalSeconds(err.retryAfter ?? 60);
        setErrorMessage('Too many attempts. Please wait before trying again.');
      } else if (err instanceof OtpApiError && err.code === 'otp_expired') {
        setStatus('awaiting_code');
        setCodeState('');
        setErrorMessage('That code expired. Send a new one.');
      } else if (err instanceof OtpApiError && err.code === 'invalid_otp') {
        setStatus('awaiting_code');
        setCodeState('');
        setErrorMessage('That code is incorrect. Try again.');
      } else if (err instanceof OtpApiError) {
        setStatus('awaiting_code');
        setErrorMessage(err.message);
      } else {
        setStatus('awaiting_code');
        setErrorMessage('Something went wrong. Please try again.');
      }
    }
  }, [code, status, phoneNumber, platform, onVerified]);

  const resend = useCallback(async () => {
    const canResendNow =
      !isResending &&
      status !== 'locked' &&
      status !== 'sending' &&
      secondsSinceSend >= MANUAL_RESEND_THRESHOLD_SECONDS &&
      resendBlockedSecondsRemaining === 0;
    if (!canResendNow) {
      return;
    }
    setIsResending(true);
    await sendCode();
    setIsResending(false);
  }, [isResending, status, secondsSinceSend, resendBlockedSecondsRemaining, sendCode]);

  return {
    code,
    setCode,
    status,
    errorMessage,
    canResend:
      status !== 'locked' &&
      status !== 'sending' &&
      !isResending &&
      secondsSinceSend >= MANUAL_RESEND_THRESHOLD_SECONDS &&
      resendBlockedSecondsRemaining === 0,
    secondsUntilResend: Math.max(
      MANUAL_RESEND_THRESHOLD_SECONDS - secondsSinceSend,
      resendBlockedSecondsRemaining,
      0,
    ),
    lockoutSecondsRemaining,
    isResending,
    resend,
    submit,
  };
}
