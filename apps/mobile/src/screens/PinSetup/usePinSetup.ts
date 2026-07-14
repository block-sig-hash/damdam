import { useCallback, useState } from 'react';
import { PinApiError, setPin as setPinRequest } from '../../api/pinClient';
import { isStrongPin } from '../../utils/pin';

export const PIN_LENGTH = 4;

export type PinSetupStage = 'enter' | 'confirm' | 'submitting';

interface UsePinSetupArgs {
  accessToken: string;
  onPinSet: () => void;
}

export interface UsePinSetupResult {
  stage: PinSetupStage;
  value: string;
  setValue: (value: string) => void;
  errorMessage: string | null;
  submit: () => Promise<void>;
}

/**
 * US-02 / prd.md §4.1 — AC-02.1 (4-digit, non-sequential, non-repeated),
 * AC-02.2 (masked, entered twice to confirm). PIN unlock (AC-02.3) and
 * lockout/recovery (AC-02.4) belong to PIN Unlock (Screen 31, not built
 * yet) — this screen only ever calls POST /auth/pin/set once, right
 * after OTP verification.
 */
export function usePinSetup({ accessToken, onPinSet }: UsePinSetupArgs): UsePinSetupResult {
  const [firstEntry, setFirstEntry] = useState('');
  const [stage, setStage] = useState<PinSetupStage>('enter');
  const [value, setValueState] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const setValue = useCallback((next: string) => {
    setErrorMessage(null);
    setValueState(next.replace(/\D/g, '').slice(0, PIN_LENGTH));
  }, []);

  const submit = useCallback(async () => {
    if (value.length !== PIN_LENGTH || stage === 'submitting') {
      return;
    }

    if (stage === 'enter') {
      if (!isStrongPin(value)) {
        setErrorMessage('Choose a non-repeated, non-sequential 4-digit PIN.');
        setValueState('');
        return;
      }
      setFirstEntry(value);
      setStage('confirm');
      setValueState('');
      return;
    }

    // stage === 'confirm'
    if (value !== firstEntry) {
      setErrorMessage("PINs didn't match. Try again.");
      setStage('enter');
      setFirstEntry('');
      setValueState('');
      return;
    }

    setStage('submitting');
    try {
      await setPinRequest(accessToken, value);
      onPinSet();
    } catch (err) {
      if (err instanceof PinApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Something went wrong. Please try again.');
      }
      setStage('enter');
      setFirstEntry('');
      setValueState('');
    }
  }, [value, stage, firstEntry, accessToken, onPinSet]);

  return { stage, value, setValue, errorMessage, submit };
}
