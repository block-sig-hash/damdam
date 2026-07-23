import { useCallback, useState } from 'react';
import { OtpApiError, requestOtp } from '../../api/authClient';
import {i18n} from '../../i18n';
import {normalizeLocale} from '../../i18n/locale';
import { digitsOnly, isValidNigerianPhoneNumber } from '../../utils/phoneNumber';

export type PhoneEntryStatus = 'idle' | 'submitting';

interface UsePhoneEntryArgs {
  onOtpSent: (phoneNumber: string) => void;
  /** AC-01.7: an existing account is directed to login, not signup. */
  onAccountExists: (phoneNumber: string) => void;
}

export interface UsePhoneEntryResult {
  phoneNumber: string;
  setPhoneNumber: (value: string) => void;
  isValid: boolean;
  status: PhoneEntryStatus;
  errorMessage: string | null;
  submit: () => Promise<void>;
}

export function usePhoneEntry({
  onOtpSent,
  onAccountExists,
}: UsePhoneEntryArgs): UsePhoneEntryResult {
  const [phoneNumber, setPhoneNumberState] = useState('');
  const [status, setStatus] = useState<PhoneEntryStatus>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const setPhoneNumber = useCallback((value: string) => {
    setErrorMessage(null);
    setPhoneNumberState(digitsOnly(value).slice(0, 11));
  }, []);

  const isValid = isValidNigerianPhoneNumber(phoneNumber);

  const submit = useCallback(async () => {
    if (!isValid || status === 'submitting') {
      return;
    }
    setStatus('submitting');
    setErrorMessage(null);
    try {
      await requestOtp(phoneNumber, normalizeLocale(i18n.language));
      onOtpSent(phoneNumber);
    } catch (err) {
      if (err instanceof OtpApiError && err.code === 'account_exists') {
        onAccountExists(phoneNumber);
      } else if (err instanceof OtpApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Something went wrong. Please try again.');
      }
    } finally {
      setStatus('idle');
    }
  }, [phoneNumber, isValid, status, onOtpSent, onAccountExists]);

  return { phoneNumber, setPhoneNumber, isValid, status, errorMessage, submit };
}
