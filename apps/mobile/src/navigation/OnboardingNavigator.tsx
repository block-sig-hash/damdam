import React, { useState } from 'react';
import { AuthResponse } from '../api/authClient';
import { OTPVerificationScreen } from '../screens/OTPVerification/OTPVerificationScreen';
import { PhoneEntryScreen } from '../screens/PhoneEntry/PhoneEntryScreen';
import { PlaceholderScreen } from '../screens/Placeholder/PlaceholderScreen';

type OnboardingStep =
  | { name: 'phone' }
  | { name: 'otp'; phoneNumber: string }
  | { name: 'existing-account'; phoneNumber: string }
  | { name: 'verified'; result: AuthResponse };

/**
 * A minimal, dependency-free stack for the two screens this task
 * covers. Deliberately not @react-navigation yet — there's no
 * benefit to the extra dependency surface until PIN Setup, Family
 * Contact, and Departure Date exist alongside these to actually
 * need routing between siblings, back-stacks, and deep links. Swap
 * this for the real navigator when those screens land.
 */
export function OnboardingNavigator(): React.JSX.Element {
  const [step, setStep] = useState<OnboardingStep>({ name: 'phone' });

  switch (step.name) {
    case 'phone':
      return (
        <PhoneEntryScreen
          onOtpSent={(phoneNumber) => setStep({ name: 'otp', phoneNumber })}
          onAccountExists={(phoneNumber) => setStep({ name: 'existing-account', phoneNumber })}
        />
      );
    case 'otp':
      return (
        <OTPVerificationScreen
          phoneNumber={step.phoneNumber}
          onVerified={(result) => setStep({ name: 'verified', result })}
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
      return (
        <PlaceholderScreen
          title={step.result.is_new_user ? "You're verified" : 'Welcome back'}
          note="Next: set up your PIN — coming in US-02."
        />
      );
  }
}
