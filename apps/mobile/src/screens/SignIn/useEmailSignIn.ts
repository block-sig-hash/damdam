import { useCallback, useState } from 'react';
import type { AuthResponse } from '../../api/authClient';
import { ApiError } from '../../api/http';
import {
  confirmEmailLogin,
  requestEmailLogin,
} from '../../api/identityClient';
import { i18n } from '../../i18n';

/**
 * Email sign-in, which is also email signup (US-29, US-37).
 *
 * There is deliberately no branch between the two before the link is opened.
 * The server answers identically for a registered and an unregistered address
 * (`identity_sent`) so that the endpoint cannot be used to test who has an
 * account, and an app that drew "welcome back" versus "create your account"
 * from the request step would reintroduce exactly that oracle in the client.
 * `is_new_user` comes back at *confirm* time, once mailbox control is proved,
 * and that is the first moment the distinction is safe to show.
 */

export const RESEND_COOLDOWN_SECONDS = 30;

// Matches the server's own EMAIL_PATTERN (apps/api/app/identity/schemas.py).
// Kept deliberately loose: this is a typo guard, not an authority on which
// addresses exist. The mail either arrives or it does not.
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function isProbablyEmail(value: string): boolean {
  return EMAIL_PATTERN.test(value.trim().toLowerCase());
}

export type SignInStage = 'email' | 'sent' | 'confirming';

export interface UseEmailSignInResult {
  stage: SignInStage;
  email: string;
  setEmail: (value: string) => void;
  code: string;
  setCode: (value: string) => void;
  busy: boolean;
  errorMessage: string | null;
  requestLink: () => Promise<void>;
  /** Confirms a token, whether typed in or handed over by a deep link. */
  confirm: (token?: string) => Promise<void>;
  restart: () => void;
}

interface UseEmailSignInOptions {
  onAuthenticated: (result: AuthResponse, email: string) => void | Promise<void>;
  initialEmail?: string;
  initialError?: string;
}

export function useEmailSignIn({
  onAuthenticated,
  initialEmail = '',
  initialError,
}: UseEmailSignInOptions): UseEmailSignInResult {
  const [stage, setStage] = useState<SignInStage>('email');
  const [email, setEmail] = useState(initialEmail);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(
    initialError ?? null,
  );

  const requestLink = useCallback(async () => {
    const normalized = email.trim().toLowerCase();
    if (!isProbablyEmail(normalized)) {
      setErrorMessage(i18n.t('signIn.emailInvalid', { ns: 'consumer' }));
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    try {
      await requestEmailLogin(
        normalized,
        i18n.language === 'fr' ? 'fr' : 'en',
      );
      setEmail(normalized);
      setStage('sent');
    } catch (error) {
      setErrorMessage(messageFor(error));
    } finally {
      setBusy(false);
    }
  }, [email]);

  const confirm = useCallback(
    async (token?: string) => {
      const raw = (token ?? code).trim();
      if (!raw) {
        return;
      }
      setBusy(true);
      setStage('confirming');
      setErrorMessage(null);
      try {
        const result = await confirmEmailLogin(raw);
        await onAuthenticated(result, email);
      } catch (error) {
        // Back to 'sent', not to 'email': the address is still right, the
        // customer simply needs another link. Sending them back to retype it
        // is the fastest way to make an expired link feel like a rejection.
        setStage('sent');
        setCode('');
        setErrorMessage(
          error instanceof ApiError &&
            (error.code === 'identity_token_expired' ||
              error.code === 'identity_token_invalid')
            ? i18n.t('signIn.linkExpired', { ns: 'consumer' })
            : messageFor(error),
        );
      } finally {
        setBusy(false);
      }
    },
    [code, email, onAuthenticated],
  );

  const restart = useCallback(() => {
    setStage('email');
    setCode('');
    setErrorMessage(null);
  }, []);

  return {
    stage,
    email,
    setEmail,
    code,
    setCode,
    busy,
    errorMessage,
    requestLink,
    confirm,
    restart,
  };
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    // The server localizes its own copy from the Accept-Language header this
    // request carried, so its message is the accurate one.
    return error.message;
  }
  return i18n.t('errors.generic', { ns: 'auth' });
}
