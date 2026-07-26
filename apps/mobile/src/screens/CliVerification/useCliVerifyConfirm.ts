import { useCallback, useState } from 'react';
import {
  CliApiError,
  confirmCliVerification,
  type VerifiedCallerIdentity,
} from '../../api/cliClient';
import { cliErrorMessage } from './cliErrorMessage';

export type CliVerifyConfirmStatus = 'awaiting_code' | 'verifying';

export const CLI_CONFIRM_CODE_LENGTH = 6;

interface UseCliVerifyConfirmArgs {
  accessToken: string;
  identityId: string;
  onConfirmed: (identity: VerifiedCallerIdentity) => void;
}

export interface UseCliVerifyConfirmResult {
  code: string;
  setCode: (value: string) => void;
  status: CliVerifyConfirmStatus;
  errorMessage: string | null;
  locked: boolean;
  submit: () => Promise<void>;
}

export function useCliVerifyConfirm({
  accessToken,
  identityId,
  onConfirmed,
}: UseCliVerifyConfirmArgs): UseCliVerifyConfirmResult {
  const [code, setCodeState] = useState('');
  const [status, setStatus] = useState<CliVerifyConfirmStatus>('awaiting_code');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);

  const setCode = useCallback((value: string) => {
    setErrorMessage(null);
    setCodeState(value.replace(/\D/g, '').slice(0, CLI_CONFIRM_CODE_LENGTH));
  }, []);

  const submit = useCallback(async () => {
    if (code.length !== CLI_CONFIRM_CODE_LENGTH || status === 'verifying' || locked) return;
    setStatus('verifying');
    setErrorMessage(null);
    try {
      const identity = await confirmCliVerification(accessToken, identityId, code);
      onConfirmed(identity);
    } catch (err) {
      if (err instanceof CliApiError && err.code === 'cli_verification_rate_limited') {
        setLocked(true);
      }
      setErrorMessage(cliErrorMessage(err));
    } finally {
      setStatus('awaiting_code');
    }
  }, [accessToken, identityId, code, status, locked, onConfirmed]);

  return { code, setCode, status, errorMessage, locked, submit };
}
