import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { AuthResponse } from '../api/authClient';
import type { RecoverySession } from '../api/identityClient';
import { AccountRecoveryScreen } from '../screens/AccountRecovery/AccountRecoveryScreen';
import { SignInScreen } from '../screens/SignIn/SignInScreen';
import { loadPendingLink, type PendingLink } from '../services/deepLinks';
import type { AuthenticatedMobileSession } from './OnboardingNavigator';

interface AuthNavigatorProps {
  onAuthenticated: (session: AuthenticatedMobileSession) => void | Promise<void>;
  /** Pre-fills the address, e.g. after "sign in with a different account". */
  initialEmail?: string;
}

type Step = { name: 'sign-in' } | { name: 'recovery'; email: string };

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
    loadPendingLink()
      .then(link => active && setPendingLink(link))
      .catch(() => undefined);
    return () => {
      active = false;
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

  return (
    <SignInScreen
      initialEmail={initialEmail}
      contextMessage={
        pendingLink?.kind === 'invitation'
          ? t('invitation.signInFirstBody')
          : undefined
      }
      onAuthenticated={(result, email) =>
        onAuthenticated(toSession(result, email))
      }
      onRecover={email => setStep({ name: 'recovery', email })}
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
