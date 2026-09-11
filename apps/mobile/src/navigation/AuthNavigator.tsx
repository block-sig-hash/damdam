import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AuthResponse } from '../api/authClient';
import { ApiError } from '../api/http';
import {
  confirmEmailLogin,
  confirmEmailRecovery,
  type RecoverySession,
} from '../api/identityClient';
import { StateMessage } from '../components/StateMessage/StateMessage';
import { AccountRecoveryScreen } from '../screens/AccountRecovery/AccountRecoveryScreen';
import { SignInScreen } from '../screens/SignIn/SignInScreen';
import {
  clearPendingLink,
  loadPendingLink,
  subscribeToDeepLinks,
  type PendingLink,
} from '../services/deepLinks';
import {
  OnboardingNavigator,
  type AuthenticatedMobileSession,
} from './OnboardingNavigator';

interface AuthNavigatorProps {
  onAuthenticated: (session: AuthenticatedMobileSession) => void | Promise<void>;
  /** Pre-fills the address, e.g. after "sign in with a different account". */
  initialEmail?: string;
}

type Step =
  | { name: 'sign-in'; initialError?: string }
  | { name: 'recovery'; email: string }
  | { name: 'phone' }
  | {
      name: 'email-link';
      kind: 'email-login' | 'email-recovery';
      token: string;
    };

/**
 * The signed-out stack (AC-37.2).
 *
 * It replaces the phone/OTP onboarding as the *default* entry point rather than
 * deleting it: `OnboardingNavigator` still serves accounts that hold a phone
 * identity, and chunk 06 kept `adopt_legacy_phone` for exactly that population.
 * What changes here is which door a new customer walks through.
 *
 * It also carries the deep-link context through. Someone who tapped an
 * invitation and landed here needs to know their link is not lost, and needs
 * the address field pre-filled with something recognizable — which is the
 * masked address, because that is all the server will disclose to an account
 * that has not proved it owns it.
 */
export function AuthNavigator({
  onAuthenticated,
  initialEmail,
}: AuthNavigatorProps): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const [step, setStep] = useState<Step>({ name: 'sign-in' });
  const [pendingLink, setPendingLink] = useState<PendingLink | null>(null);

  useEffect(() => {
    let active = true;
    const route = (link: PendingLink) => {
      if (!active) {
        return;
      }
      if (link.kind === 'email-login' || link.kind === 'email-recovery') {
        setStep({ name: 'email-link', kind: link.kind, token: link.token });
      } else {
        setPendingLink(link);
      }
    };
    loadPendingLink()
      .then(link => {
        if (link) {
          route(link);
        }
      })
      .catch(() => undefined);
    const unsubscribe = subscribeToDeepLinks(route);
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  if (step.name === 'recovery') {
    return (
      <AccountRecoveryScreen
        initialEmail={step.email}
        onRecovered={session => onAuthenticated(toSession(session))}
        onCancel={() => setStep({ name: 'sign-in' })}
      />
    );
  }

  if (step.name === 'email-link') {
    return (
      <EmailLinkHandoff
        kind={step.kind}
        token={step.token}
        onAuthenticated={onAuthenticated}
        onFailed={message =>
          setStep({ name: 'sign-in', initialError: message })
        }
      />
    );
  }

  if (step.name === 'phone') {
    return (
      <OnboardingNavigator
        onAuthenticated={onAuthenticated}
        onCancel={() => setStep({ name: 'sign-in' })}
      />
    );
  }

  return (
    <SignInScreen
      initialEmail={initialEmail}
      initialError={step.initialError}
      contextMessage={
        pendingLink?.kind === 'invitation'
          ? t('invitation.signInFirstBody')
          : undefined
      }
      onAuthenticated={(result, email) =>
        onAuthenticated(toSession(result, email))
      }
      onRecover={email => setStep({ name: 'recovery', email })}
      onUsePhone={() => setStep({ name: 'phone' })}
    />
  );
}

function EmailLinkHandoff({
  kind,
  token,
  onAuthenticated,
  onFailed,
}: {
  kind: 'email-login' | 'email-recovery';
  token: string;
  onAuthenticated: (session: AuthenticatedMobileSession) => void | Promise<void>;
  onFailed: (message: string) => void;
}): React.JSX.Element {
  const { t } = useTranslation('consumer');

  useEffect(() => {
    let active = true;
    const confirm =
      kind === 'email-login' ? confirmEmailLogin(token) : confirmEmailRecovery(token);
    confirm
      .then(async result => {
        await clearPendingLink().catch(() => undefined);
        if (active) {
          await onAuthenticated(toSession(result));
        }
      })
      .catch(async error => {
        await clearPendingLink().catch(() => undefined);
        if (!active) {
          return;
        }
        onFailed(
          error instanceof ApiError &&
            (error.code === 'identity_token_expired' ||
              error.code === 'identity_token_invalid')
            ? t('signIn.linkExpired')
            : error instanceof ApiError
              ? error.message
              : t('home.unavailableBody'),
        );
      });
    return () => {
      active = false;
    };
  }, [kind, onAuthenticated, onFailed, t, token]);

  return (
    <StateMessage
      variant="pending"
      title={t('signIn.signingIn')}
      body={t('signIn.linkOpening')}
      testID="email-link-confirming"
    />
  );
}

function toSession(
  result: AuthResponse | RecoverySession,
  email?: string,
): AuthenticatedMobileSession {
  return {
    userId: result.user.id,
    accessToken: result.access_token,
    refreshToken: result.refresh_token,
    phoneNumber: result.user.phone_number ?? null,
    // The address the customer typed, when there is one: `user.email` is the
    // legacy profile column and is not necessarily the verified identifier they
    // just signed in with.
    email: email ?? result.user.email ?? null,
    departureDate: result.user.departure_date ?? null,
    locale: result.user.locale,
  };
}
