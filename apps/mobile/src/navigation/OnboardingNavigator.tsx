import React, { useState } from 'react';
import { AuthResponse } from '../api/authClient';
import { ActivationCodeEntryScreen } from '../screens/ActivationCodeEntry/ActivationCodeEntryScreen';
import { ActivationSuccessScreen } from '../screens/ActivationSuccess/ActivationSuccessScreen';
import { OTPVerificationScreen } from '../screens/OTPVerification/OTPVerificationScreen';
import { PhoneEntryScreen } from '../screens/PhoneEntry/PhoneEntryScreen';
import { PlaceholderScreen } from '../screens/Placeholder/PlaceholderScreen';

type OnboardingStep =
  | { name: 'activation-entry' }
  | { name: 'phone'; activationCode?: string }
  | { name: 'otp'; phoneNumber: string; activationCode?: string }
  | { name: 'existing-account'; phoneNumber: string }
  | { name: 'verified'; result: AuthResponse; activationCode?: string }
  | { name: 'activated' };

interface OnboardingNavigatorProps {
  /**
   * US-07 / Flow B (docs/frontend-mobile.md §8.2) — models what a
   * deep-link handler would pass in from the HTO's WhatsApp message.
   * This component doesn't itself register the OS-level URL scheme.
   */
  initialActivationCode?: string;
}

/**
 * A minimal, dependency-free stack for the screens this task covers.
 * Deliberately not @react-navigation yet — there's no benefit to the
 * extra dependency surface until PIN Setup, Family Contact, and
 * Departure Date exist alongside these to actually need routing
 * between siblings, back-stacks, and deep links. Swap this for the
 * real navigator when those screens land.
 */
export function OnboardingNavigator({
  initialActivationCode,
}: OnboardingNavigatorProps = {}): React.JSX.Element {
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
          onAccountExists={(phoneNumber) => setStep({ name: 'existing-account', phoneNumber })}
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
      return (
        <PlaceholderScreen
          title="Welcome back"
          note="This number already has an account. Log in with your PIN — coming in US-02."
        />
      );
    case 'verified':
      // AC-07.4: OTP → PIN → package auto-attached via code. PIN
      // Setup isn't built yet (tracked separately, US-02's mobile
      // screen), so a pilgrim who arrived with an activation code
      // redeems it here rather than waiting on a screen that doesn't
      // exist; one that arrived without a code sees the pre-existing
      // "coming in US-02" placeholder unchanged.
      if (step.activationCode) {
        return (
          <ActivationSuccessScreen
            accessToken={step.result.access_token}
            activationCode={step.activationCode}
            onContinue={() => setStep({ name: 'activated' })}
          />
        );
      }
      return (
        <PlaceholderScreen
          title={step.result.is_new_user ? "You're verified" : 'Welcome back'}
          note="Next: set up your PIN — coming in US-02."
        />
      );
    case 'activated':
      return (
        <PlaceholderScreen
          title="Package active"
          note="Next: PIN setup, family contact, and departure date — coming in later stories."
        />
      );
  }
}
