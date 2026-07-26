import { useCallback, useState } from 'react';
import { captureCliConsent, type VerifiedCallerIdentity } from '../../api/cliClient';
import { cliErrorMessage } from './cliErrorMessage';

/** Matches the consent copy shown below -- bump alongside any copy change. */
export const CLI_CONSENT_VERSION = 'v1';

export type CliConsentStatus = 'idle' | 'submitting';

interface UseCliConsentArgs {
  accessToken: string;
  identityId: string;
  onConsented: (identity: VerifiedCallerIdentity) => void;
}

export interface UseCliConsentResult {
  status: CliConsentStatus;
  errorMessage: string | null;
  submit: () => Promise<void>;
}

export function useCliConsent({
  accessToken,
  identityId,
  onConsented,
}: UseCliConsentArgs): UseCliConsentResult {
  const [status, setStatus] = useState<CliConsentStatus>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (status === 'submitting') return;
    setStatus('submitting');
    setErrorMessage(null);
    try {
      const identity = await captureCliConsent(accessToken, identityId, CLI_CONSENT_VERSION);
      onConsented(identity);
    } catch (err) {
      setErrorMessage(cliErrorMessage(err));
    } finally {
      setStatus('idle');
    }
  }, [accessToken, identityId, status, onConsented]);

  return { status, errorMessage, submit };
}
