/**
 * The one place to register a new screenshot target. Each key becomes
 * a button on the harness picker screen (testID `harness-target-<key>`)
 * and a `render()` that mounts the real screen component with fixture
 * props/data -- see screenshotHarness/README.md for how to add one.
 */
import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import { OTPVerificationScreen } from '../src/screens/OTPVerification/OTPVerificationScreen';
import { PinUnlockScreen } from '../src/screens/PinUnlock/PinUnlockScreen';
import { PinSetupScreen } from '../src/screens/PinSetup/PinSetupScreen';
import { ActivationCodeEntryScreen } from '../src/screens/ActivationCodeEntry/ActivationCodeEntryScreen';
import { PackageSelectionScreen } from '../src/screens/PackageSelection/PackageSelectionScreen';
import { EsimQrCodeScreen } from '../src/screens/EsimSetup/EsimQrCodeScreen';
import { EsimActivationPromptScreen } from '../src/screens/EsimActivation/EsimActivationPromptScreen';
import { EsimActivationGuideScreen } from '../src/screens/EsimActivation/EsimActivationGuideScreen';
import { ActivationSuccessScreen } from '../src/screens/ActivationSuccess/ActivationSuccessScreen';
import { SosConfirmScreen } from '../src/screens/SosConfirm/SosConfirmScreen';
import { SosSentScreen } from '../src/screens/SosSent/SosSentScreen';
import { DialPadScreen } from '../src/screens/DialPad/DialPadScreen';
import { ActiveCallScreen } from '../src/screens/ActiveCall/ActiveCallScreen';
import { savePinLocally } from '../src/utils/pinLocalStore';
import {
  FIXTURE_ACCESS_TOKEN,
  FIXTURE_PACKAGE_ID,
  FIXTURE_PHONE_NUMBER,
  createFixtureCallSession,
} from './fixtures';

const noop = () => undefined;

/**
 * PinUnlockScreen's stage depends on react-native-keychain state that's
 * read asynchronously on mount -- seed a fixture PIN first so the
 * screen resolves to its normal digit-entry state ('entry') rather
 * than 'no-local-pin' (a fresh install has no locally-stored PIN).
 */
function PinUnlockTarget(): React.JSX.Element {
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    savePinLocally('1234')
      .catch(() => undefined)
      .finally(() => setSeeded(true));
  }, []);
  if (!seeded) return <View />;
  return <PinUnlockScreen phoneNumber={FIXTURE_PHONE_NUMBER} onUnlocked={noop} />;
}

export interface HarnessTarget {
  label: string;
  render: () => React.JSX.Element;
}

export const HARNESS_REGISTRY: Record<string, HarnessTarget> = {
  'otp-verification': {
    label: 'OTP Verification',
    render: () => (
      <OTPVerificationScreen phoneNumber={FIXTURE_PHONE_NUMBER} onVerified={noop} />
    ),
  },
  'pin-unlock': {
    label: 'PIN Unlock',
    render: () => <PinUnlockTarget />,
  },
  'pin-setup': {
    label: 'PIN Setup',
    render: () => (
      <PinSetupScreen accessToken={FIXTURE_ACCESS_TOKEN} onPinSet={noop} />
    ),
  },
  'activation-code-entry': {
    label: 'Activation Code Entry',
    render: () => <ActivationCodeEntryScreen onContinue={noop} />,
  },
  'package-selection': {
    label: 'Package Selection',
    render: () => <PackageSelectionScreen onSelectTier={noop} />,
  },
  'esim-qr-code': {
    label: 'eSIM QR Code',
    render: () => (
      <EsimQrCodeScreen accessToken={FIXTURE_ACCESS_TOKEN} packageId={FIXTURE_PACKAGE_ID} />
    ),
  },
  'esim-activation-prompt-android': {
    label: 'eSIM Activation Prompt (Android automatic path)',
    render: () => (
      <EsimActivationPromptScreen
        activationPath="single_tap"
        onActivate={noop}
        onManualGuide={noop}
      />
    ),
  },
  'esim-activation-guide-ios': {
    label: 'eSIM Activation Guide (iOS manual-only path)',
    render: () => (
      <EsimActivationGuideScreen
        platform="ios"
        deviceModel="iPhone 14"
        onShowQrCode={noop}
        onConfirmActivated={noop}
      />
    ),
  },
  'activation-success': {
    label: 'Activation Success',
    render: () => (
      <ActivationSuccessScreen
        accessToken={FIXTURE_ACCESS_TOKEN}
        activationCode="HARNESS01"
        onContinue={noop}
      />
    ),
  },
  'sos-confirm': {
    label: 'SOS Confirm',
    render: () => <SosConfirmScreen onConfirmed={noop} />,
  },
  'sos-sent': {
    label: 'SOS Sent',
    render: () => (
      <SosSentScreen
        synced
        htoPhone="+2348011112222"
        timestamp={new Date().toISOString()}
        onCancel={noop}
      />
    ),
  },
  'dial-pad': {
    label: 'Dial Pad',
    render: () => (
      <DialPadScreen
        accessToken={FIXTURE_ACCESS_TOKEN}
        pstnMinutesRemaining={30}
        onCallStarted={noop}
        voiceGateway={{ startCall: () => Promise.reject(new Error('not used in harness')) }}
        contactsLoader={() => Promise.resolve([])}
        callingReadiness={() => Promise.resolve()}
      />
    ),
  },
  'active-call': {
    label: 'Active Call (in-app state; not the native CallKit/ConnectionService UI -- see README)',
    render: () => (
      <ActiveCallScreen
        call={createFixtureCallSession()}
        recipientName="Amina Yusuf"
        onFinished={noop}
      />
    ),
  },
};
