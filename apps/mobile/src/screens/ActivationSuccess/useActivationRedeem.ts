import { useCallback, useEffect, useState } from 'react';
import {
  ActivationApiError,
  ActivationRedemption,
  redeemActivationCode,
} from '../../api/activationClient';

export type ActivationRedeemStatus = 'redeeming' | 'success' | 'error';

interface UseActivationRedeemArgs {
  accessToken: string;
  activationCode: string;
}

export interface UseActivationRedeemResult {
  status: ActivationRedeemStatus;
  result: ActivationRedemption | null;
  errorMessage: string | null;
  retry: () => Promise<void>;
}

/**
 * US-07 / prd.md §4.2 — AC-07.4/AC-07.5's "package auto-attached":
 * redemption fires as soon as this screen mounts, without a separate
 * user action, for both the new-pilgrim (just finished OTP/PIN) and
 * existing-pilgrim (already signed in) paths — the backend contract
 * is identical for both (api-spec.md §7.19).
 */
export function useActivationRedeem({
  accessToken,
  activationCode,
}: UseActivationRedeemArgs): UseActivationRedeemResult {
  const [status, setStatus] = useState<ActivationRedeemStatus>('redeeming');
  const [result, setResult] = useState<ActivationRedemption | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const redeem = useCallback(async () => {
    setStatus('redeeming');
    setErrorMessage(null);
    try {
      const redemption = await redeemActivationCode(accessToken, activationCode);
      setResult(redemption);
      setStatus('success');
    } catch (err) {
      setStatus('error');
      if (err instanceof ActivationApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Something went wrong. Please try again.');
      }
    }
  }, [accessToken, activationCode]);

  useEffect(() => {
    redeem();
    // Only re-run via explicit retry(), not on every accessToken/code
    // identity change — those are stable for this screen's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { status, result, errorMessage, retry: redeem };
}
