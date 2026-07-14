import { useCallback, useState } from 'react';
import {
  ActivationApiError,
  ActivationPreview,
  previewActivationCode,
} from '../../api/activationClient';

export const ACTIVATION_CODE_LENGTH = 8;

export type ActivationCodeEntryStatus = 'idle' | 'checking' | 'valid' | 'invalid';

interface UseActivationCodeEntryArgs {
  initialCode?: string;
}

export interface UseActivationCodeEntryResult {
  code: string;
  setCode: (value: string) => void;
  status: ActivationCodeEntryStatus;
  preview: ActivationPreview | null;
  errorMessage: string | null;
  canContinue: boolean;
  checkCode: () => Promise<void>;
}

function normalizeCode(value: string): string {
  return value
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .slice(0, ACTIVATION_CODE_LENGTH);
}

/**
 * US-07 / prd.md §4.2 — AC-07.2 (preview before commitment). Screen
 * 13 of the onboarding flow (docs/frontend-mobile.md §8.1), entry
 * point for Flow B (§8.2). `initialCode` models what a deep-link
 * handler would pass in — this screen doesn't itself register the
 * OS-level URL scheme.
 */
export function useActivationCodeEntry({
  initialCode,
}: UseActivationCodeEntryArgs): UseActivationCodeEntryResult {
  const [code, setCodeState] = useState(() => normalizeCode(initialCode ?? ''));
  const [status, setStatus] = useState<ActivationCodeEntryStatus>('idle');
  const [preview, setPreview] = useState<ActivationPreview | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const setCode = useCallback((value: string) => {
    setErrorMessage(null);
    setPreview(null);
    setStatus('idle');
    setCodeState(normalizeCode(value));
  }, []);

  const checkCode = useCallback(async () => {
    if (code.length !== ACTIVATION_CODE_LENGTH || status === 'checking') {
      return;
    }
    setStatus('checking');
    setErrorMessage(null);
    try {
      const result = await previewActivationCode(code);
      setPreview(result);
      if (result.valid) {
        setStatus('valid');
        return;
      }
      setStatus('invalid');
      setErrorMessage(
        result.reason === 'activation_code_already_used'
          ? 'This activation code has already been used.'
          : 'This activation code has expired. Ask your HTO for a new one.',
      );
    } catch (err) {
      setPreview(null);
      setStatus('invalid');
      if (err instanceof ActivationApiError && err.code === 'activation_code_invalid') {
        setErrorMessage("That code doesn't look right. Check it and try again.");
      } else if (err instanceof ActivationApiError) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage('Something went wrong. Please try again.');
      }
    }
  }, [code, status]);

  return {
    code,
    setCode,
    status,
    preview,
    errorMessage,
    canContinue: status === 'valid',
    checkCode,
  };
}
