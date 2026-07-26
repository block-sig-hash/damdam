import { useCallback, useEffect, useRef, useState } from 'react';
import { AuthResponse, OtpApiError, Platform, requestOtp, verifyOtp } from '../../api/authClient';
import { useCountdownSeconds } from '../../hooks/useCountdownSeconds';
import { useElapsedSeconds } from '../../hooks/useElapsedSeconds';
import {i18n} from '../../i18n';
import {normalizeLocale} from '../../i18n/locale';

/**
 * AC-01.9: "Sending your code..." after 10s, manual resend from 30s —
 * both independent of the backend's own 180s provider-failover
 * threshold (apps/api/app/config.py otp_failover_threshold_seconds),
 * which the pilgrim never sees directly.
 */
const SENDING_REASSURANCE_THRESHOLD_SECONDS = 10;
const MANUAL_RESEND_THRESHOLD_SECONDS = 30;
const OTP_CODE_LENGTH = 6;

export type OtpVerificationStatus = 'awaiting_code' | 'verifying' | 'locked';

interface UseOtpVerificationArgs {
  phoneNumber: string;
  platform: Platform;
  onVerified: (result: AuthResponse) => void;
}

export interface UseOtpVerificationResult {
  code: string;
  setCode: (value: string) => void;
  status: OtpVerificationStatus;
  errorMessage: string | null;
  showSendingReassurance: boolean;
  canResend: boolean;
  secondsUntilResend: number;
  lockoutSecondsRemaining: number;
  isResending: boolean;
  resend: () => Promise<void>;
  submit: () => Promise<void>;
}

export function useOtpVerification({
  phoneNumber,
  platform,
  onVerified,
}: UseOtpVerificationArgs): UseOtpVerificationResult {
  const [sentAt, setSentAt] = useState(() => Date.now());
  const [code, setCodeState] = useState('');
  const [status, setStatus] = useState<OtpVerificationStatus>('awaiting_code');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lockoutTotalSeconds, setLockoutTotalSeconds] = useState(0);
  const [resendBlockedTotalSeconds, setResendBlockedTotalSeconds] = useState(0);
  const [isResending, setIsResending] = useState(false);

  const secondsSinceSend = useElapsedSeconds(sentAt);
  const lockoutSecondsRemaining = useCountdownSeconds(lockoutTotalSeconds);
  const resendBlockedSecondsRemaining = useCountdownSeconds(resendBlockedTotalSeconds);

  // useCountdownSeconds' `remaining` state lags `lockoutTotalSeconds` by one
  // render (its useState initializer only applies on first mount; the
  // effect that resyncs it to a new prop value runs after commit). Without
  // this latch, the render where lockoutTotalSeconds first becomes >0 but
  // lockoutSecondsRemaining is still its previous 0 would immediately
  // "expire" a lockout that hasn't started counting down yet.
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
      const result = await verifyOtp(
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
        setErrorMessage(i18n.t('errors.tooManyAttempts', {ns: 'auth'}));
      } else if (err instanceof OtpApiError && err.code === 'otp_expired') {
        setStatus('awaiting_code');
        setCodeState('');
        setErrorMessage(i18n.t('errors.expiredCode', {ns: 'auth'}));
      } else if (err instanceof OtpApiError && err.code === 'invalid_otp') {
        setStatus('awaiting_code');
        setCodeState('');
        setErrorMessage(i18n.t('errors.incorrectCode', {ns: 'auth'}));
      } else if (err instanceof OtpApiError) {
        setStatus('awaiting_code');
        setErrorMessage(err.message);
      } else {
        setStatus('awaiting_code');
        setErrorMessage(i18n.t('errors.generic', {ns: 'auth'}));
      }
    }
  }, [code, status, phoneNumber, platform, onVerified]);

  const resend = useCallback(async () => {
    const canResendNow =
      !isResending &&
      status !== 'locked' &&
      secondsSinceSend >= MANUAL_RESEND_THRESHOLD_SECONDS &&
      resendBlockedSecondsRemaining === 0;
    if (!canResendNow) {
      return;
    }
    setIsResending(true);
    setErrorMessage(null);
    try {
      await requestOtp(phoneNumber, normalizeLocale(i18n.language));
      setSentAt(Date.now());
      setCodeState('');
      setStatus('awaiting_code');
    } catch (err) {
      if (err instanceof OtpApiError && err.code === 'rate_limited') {
        setResendBlockedTotalSeconds(err.retryAfter ?? MANUAL_RESEND_THRESHOLD_SECONDS);
        setErrorMessage(i18n.t('errors.waitBeforeCode', {ns: 'auth'}));
      } else if (err instanceof OtpApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage(i18n.t('errors.generic', {ns: 'auth'}));
      }
    } finally {
      setIsResending(false);
    }
  }, [isResending, status, phoneNumber, secondsSinceSend, resendBlockedSecondsRemaining]);

  return {
    code,
    setCode,
    status,
    errorMessage,
    showSendingReassurance:
      status === 'awaiting_code' && secondsSinceSend >= SENDING_REASSURANCE_THRESHOLD_SECONDS,
    canResend:
      status !== 'locked' &&
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
