import React, { useEffect, useState } from 'react';
import {useTranslation} from 'react-i18next';
import { AuthResponse } from '../api/authClient';
import { ActivationCodeEntryScreen } from '../screens/ActivationCodeEntry/ActivationCodeEntryScreen';
import { ActivationSuccessScreen } from '../screens/ActivationSuccess/ActivationSuccessScreen';
import { OTPVerificationScreen } from '../screens/OTPVerification/OTPVerificationScreen';
import { PhoneEntryScreen } from '../screens/PhoneEntry/PhoneEntryScreen';
import { PinSetupScreen } from '../screens/PinSetup/PinSetupScreen';
import { PlaceholderScreen } from '../screens/Placeholder/PlaceholderScreen';
import { ReturningPilgrimScreen } from '../screens/ReturningPilgrim/ReturningPilgrimScreen';

type OnboardingStep =
  | { name: 'activation-entry' }
  | { name: 'phone'; activationCode?: string }
  | { name: 'otp'; phoneNumber: string; activationCode?: string }
  | { name: 'existing-account'; phoneNumber: string; activationCode?: string }
  | { name: 'verified'; result: AuthResponse; activationCode?: string }
  | {
      name: 'activated';
      /** US-30 AC-30.4: carried so the authenticated session can own its queues. */
      userId?: string;
      accessToken: string;
      refreshToken: string;
      phoneNumber: string;
      isNewUser: boolean;
      departureDate: string | null;
      packageId: string;
      locale: 'en' | 'fr';
    }
  | { name: 'onboarded' };

export interface AuthenticatedMobileSession {
  /** US-30 AC-30.4: owner of anything this device queues offline. */
  userId?: string;
  accessToken: string;
  /** AC-23.1/AC-23.2: needed by the session-persistence layer (useSessionGate)
   * to exchange for a fresh access token without forcing re-authentication. */
  refreshToken: string;
  /** AC-23.3: PinUnlockScreen's "forgot your PIN" OTP-recovery path needs this. */
  phoneNumber: string;
  departureDate: string | null;
  packageId?: string;
  locale: 'en' | 'fr';
}

interface OnboardingNavigatorProps {
  /**
   * US-07 / Flow B (docs/frontend-mobile.md §8.2) — models what a
   * deep-link handler would pass in from the HTO's WhatsApp message.
   * This component doesn't itself register the OS-level URL scheme.
   */
  initialActivationCode?: string;
  /** Hands the authenticated session to the app host without changing onboarding screens. */
  onAuthenticated?: (session: AuthenticatedMobileSession) => void;
}

function AuthenticationHandoff({
  session,
  onAuthenticated,
  title,
}: {
  session: AuthenticatedMobileSession;
  onAuthenticated?: (session: AuthenticatedMobileSession) => void;
  title: string;
}): React.JSX.Element {
  const {t} = useTranslation('common');
  useEffect(() => {
    onAuthenticated?.(session);
  }, [onAuthenticated, session]);
  return <PlaceholderScreen title={title} note={t('onboarding.openingHome')} />;
}

/**
 * A minimal, dependency-free stack for the screens this task covers.
 * Deliberately not @react-navigation yet — there's no benefit to the
 * extra dependency surface until Family Contact and Departure Date
 * exist alongside these to actually need routing between siblings,
 * back-stacks, and deep links. Swap this for the real navigator when
 * those screens land.
 */
export function OnboardingNavigator({
  initialActivationCode,
  onAuthenticated,
}: OnboardingNavigatorProps = {}): React.JSX.Element {
  const {t} = useTranslation('common');
  const [step, setStep] = useState<OnboardingStep>(
    initialActivationCode ? { name: 'activation-entry' } : { name: 'phone' },
  );

  switch (step.name) {
    case 'activation-entry':
      return (
        <ActivationCodeEntryScreen
          initialCode={initialActivationCode}
          onContinue={(activationCode) => setStep({ name: 'phone', activationCode })}
        />
      );
    case 'phone':
      return (
        <PhoneEntryScreen
          onOtpSent={(phoneNumber) =>
            setStep({ name: 'otp', phoneNumber, activationCode: step.activationCode })
          }
          onAccountExists={(phoneNumber) =>
            setStep({ name: 'existing-account', phoneNumber, activationCode: step.activationCode })
          }
        />
      );
    case 'otp':
      return (
        <OTPVerificationScreen
          phoneNumber={step.phoneNumber}
          onVerified={(result) =>
            setStep({ name: 'verified', result, activationCode: step.activationCode })
          }
        />
      );
    case 'existing-account':
      // AC-01.7 / AC-07.5 / AC-23.4: no valid local session for this
      // phone number (new device, or the 30-day session expired) —
      // ReturningPilgrimScreen re-authenticates via OTP-based
      // recovery (there's no phone+PIN login endpoint; PIN is a
      // local-only unlock gate per AC-23.5) and rejoins the same
      // 'verified' handling a fresh signup uses, activation code and
      // all.
      return (
        <ReturningPilgrimScreen
          phoneNumber={step.phoneNumber}
          onVerified={(result) =>
            setStep({ name: 'verified', result, activationCode: step.activationCode })
          }
        />
      );
    case 'verified':
      // AC-07.4/AC-07.5: OTP or recovery → package auto-attached via
      // code. A pilgrim who arrived with an activation code redeems
      // it immediately (before PIN Setup) so this rather-early screen
      // isn't waiting on anything; one that arrived without a code
      // goes straight into PIN Setup — but only for a genuinely new
      // pilgrim. 'verified' is reached by both the 'otp' path (always
      // a new signup, since 'phone' routes an existing number to
      // 'existing-account' instead) and the 'existing-account' path
      // (ReturningPilgrimScreen, always a returning pilgrim who
      // already has a PIN) — is_new_user is what actually
      // distinguishes them here, not which step led to 'verified'.
      if (step.activationCode) {
        return (
          <ActivationSuccessScreen
            accessToken={step.result.access_token}
            activationCode={step.activationCode}
            onContinue={(redemption) =>
              setStep({
                name: 'activated',
                userId: step.result.user.id,
                accessToken: step.result.access_token,
                refreshToken: step.result.refresh_token,
                phoneNumber: step.result.user.phone_number,
                isNewUser: step.result.is_new_user,
                departureDate: step.result.user.departure_date ?? null,
                packageId: redemption.package_id,
                locale: step.result.user.locale,
              })
            }
          />
        );
      }
      if (!step.result.is_new_user) {
        return (
          <AuthenticationHandoff
            session={{
              userId: step.result.user.id,
              accessToken: step.result.access_token,
              refreshToken: step.result.refresh_token,
              phoneNumber: step.result.user.phone_number,
              departureDate: step.result.user.departure_date ?? null,
              locale: step.result.user.locale,
            }}
            onAuthenticated={onAuthenticated}
            title={t('onboarding.welcomeBack')}
          />
        );
      }
      return (
        <PinSetupScreen
          accessToken={step.result.access_token}
          onPinSet={() => {
            if (onAuthenticated) {
              onAuthenticated({
                userId: step.result.user.id,
                accessToken: step.result.access_token,
                refreshToken: step.result.refresh_token,
                phoneNumber: step.result.user.phone_number,
                departureDate: step.result.user.departure_date ?? null,
                locale: step.result.user.locale,
              });
            } else {
              setStep({ name: 'onboarded' });
            }
          }}
        />
      );
    case 'activated':
      // Same is_new_user branch as 'verified' above: a returning
      // pilgrim redeeming a fresh activation code (e.g. a new
      // package on a device they'd already onboarded from) already
      // has a PIN and must not be routed back through PIN Setup.
      if (!step.isNewUser) {
        return (
          <AuthenticationHandoff
            session={{
              userId: step.userId,
              accessToken: step.accessToken,
              refreshToken: step.refreshToken,
              phoneNumber: step.phoneNumber,
              departureDate: step.departureDate,
              packageId: step.packageId,
              locale: step.locale,
            }}
            onAuthenticated={onAuthenticated}
            title={t('onboarding.packageActive')}
          />
        );
      }
      return (
        <PinSetupScreen
          accessToken={step.accessToken}
          onPinSet={() => {
            if (onAuthenticated) {
              onAuthenticated({
                userId: step.userId,
                accessToken: step.accessToken,
                refreshToken: step.refreshToken,
                phoneNumber: step.phoneNumber,
                departureDate: step.departureDate,
                packageId: step.packageId,
                locale: step.locale,
              });
            } else {
              setStep({ name: 'onboarded' });
            }
          }}
        />
      );
    case 'onboarded':
      return (
        <PlaceholderScreen
          title={t('onboarding.pinSet')}
          note={t('onboarding.nextSteps')}
        />
      );
  }
}
