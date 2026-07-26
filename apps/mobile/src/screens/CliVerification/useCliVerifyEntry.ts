import { useCallback, useState } from 'react';
import { startCliVerification, type VerifiedCallerIdentity } from '../../api/cliClient';
import { cliDigitsOnly, isValidCliPhoneNumber } from '../../utils/cliPhoneNumber';
import { cliErrorMessage } from './cliErrorMessage';

export type CliVerifyEntryStatus = 'idle' | 'submitting';

interface UseCliVerifyEntryArgs {
  accessToken: string;
  onStarted: (identity: VerifiedCallerIdentity) => void;
}

export interface UseCliVerifyEntryResult {
  phoneNumber: string;
  setPhoneNumber: (value: string) => void;
  isValid: boolean;
  status: CliVerifyEntryStatus;
  errorMessage: string | null;
  submit: () => Promise<void>;
}

/** AC-14.1/AC-14.10: verifies any Nigerian number, independent of login. */
export function useCliVerifyEntry({
  accessToken,
  onStarted,
}: UseCliVerifyEntryArgs): UseCliVerifyEntryResult {
  const [phoneNumber, setPhoneNumberState] = useState('');
  const [status, setStatus] = useState<CliVerifyEntryStatus>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const setPhoneNumber = useCallback((value: string) => {
    setErrorMessage(null);
    setPhoneNumberState(cliDigitsOnly(value).slice(0, 11));
  }, []);

  const isValid = isValidCliPhoneNumber(phoneNumber);

  const submit = useCallback(async () => {
    if (!isValid || status === 'submitting') return;
    setStatus('submitting');
    setErrorMessage(null);
    try {
      const identity = await startCliVerification(accessToken, phoneNumber);
      onStarted(identity);
    } catch (err) {
      setErrorMessage(cliErrorMessage(err));
    } finally {
      setStatus('idle');
    }
  }, [accessToken, phoneNumber, isValid, status, onStarted]);

  return { phoneNumber, setPhoneNumber, isValid, status, errorMessage, submit };
}
