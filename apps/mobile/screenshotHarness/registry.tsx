/**
 * The one place to register a new screenshot target. Each key becomes
 * a button on the harness picker screen (testID `harness-target-<key>`)
 * and a `render()` that mounts the real screen component with fixture
 * props/data -- see screenshotHarness/README.md for how to add one.
 */
import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
import { ConsumerHomeScreen } from '../src/screens/ConsumerHome/ConsumerHomeScreen';
import { SignInScreen } from '../src/screens/SignIn/SignInScreen';
import { GALLERY_SECTIONS, GalleryScreen } from '../src/screens/Gallery/GalleryScreen';
import { PlanListScreen } from '../src/screens/Purchase/PlanListScreen';
import { QuoteReviewScreen } from '../src/screens/Purchase/QuoteReviewScreen';
import { OrderStatusScreen } from '../src/screens/Purchase/OrderStatusScreen';
import { savePinLocally } from '../src/utils/pinLocalStore';
import {
  FIXTURE_ACCESS_TOKEN,
  FIXTURE_DEVICE_CHECKED,
  FIXTURE_DEVICE_INCAPABLE,
  FIXTURE_MARKET,
  FIXTURE_ORDER,
  FIXTURE_ORDER_AWAITING_WEBHOOK,
  FIXTURE_ORDER_DECLINED,
  FIXTURE_PACKAGE_ID,
  FIXTURE_PAYMENT_METHODS,
  FIXTURE_PAYMENT_METHODS_BLOCKED,
  FIXTURE_PHONE_NUMBER,
  FIXTURE_PRODUCT,
  FIXTURE_PRODUCT_DEVICE_BLOCKED,
  FIXTURE_QUOTE,
} from './fixtures';

const noop = () => undefined;

/**
 * PinUnlockScreen's stage depends on react-native-keychain state that's
 * read asynchronously on mount -- seed a fixture PIN first so the
 * screen resolves to its normal digit-entry state ('entry') rather
 * than 'no-local-pin' (a fresh install has no locally-stored PIN).
 */
const FIXTURE_USER_ID = 'fixture-0000-4000-8000-000000000001';

function PinUnlockTarget(): React.JSX.Element {
  const [seeded, setSeeded] = useState(false);
  useEffect(() => {
    savePinLocally(FIXTURE_USER_ID, '1234')
      .catch(() => undefined)
      .finally(() => setSeeded(true));
  }, []);
  if (!seeded) return <View />;
  return <PinUnlockScreen
      phoneNumber={FIXTURE_PHONE_NUMBER}
      userId={FIXTURE_USER_ID}
      onUnlocked={noop}
    />;
}

function ConsumerHomeErrorTarget(): React.JSX.Element {
  const { t } = useTranslation('consumer');
  return (
    <ConsumerHomeScreen
      serviceState="none"
      services={[]}
      loading={false}
      errorMessage={t('home.unavailableBody')}
      onRetry={noop}
      onBrowsePlans={noop}
      onOpenMyLine={noop}
      onOpenOrder={noop}
    />
  );
}

export interface HarnessTarget {
  label: string;
  render: () => React.JSX.Element;
}

/**
 * The design system's own targets (chunk 08).
 *
 * One entry per gallery section rather than one for the whole gallery: a
 * full-page capture of every state at phone width is unreadable, and an
 * unreadable screenshot is not evidence of anything. Generated from
 * `GALLERY_SECTIONS` so adding a section to the gallery adds it to the matrix
 * -- there is no second list to forget.
 */
const GALLERY_TARGETS: Record<string, HarnessTarget> = Object.fromEntries(
  GALLERY_SECTIONS.map(section => [
    `gallery-${section}`,
    {
      label: `Design system — ${section}`,
      render: () => <GalleryScreen only={section} />,
    },
  ]),
);

export const HARNESS_REGISTRY: Record<string, HarnessTarget> = {
  ...GALLERY_TARGETS,
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
      <PinSetupScreen
      accessToken={FIXTURE_ACCESS_TOKEN}
      userId={FIXTURE_USER_ID}
      onPinSet={noop}
    />
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
  'consumer-sign-in': {
    label: 'Consumer sign in',
    render: () => (
      <SignInScreen
        onAuthenticated={noop}
        onRecover={noop}
        onUsePhone={noop}
      />
    ),
  },
  'consumer-home-no-service': {
    label: 'Consumer Home — no service',
    render: () => (
      <ConsumerHomeScreen
        serviceState="none"
        services={[]}
        loading={false}
        errorMessage={null}
        onRetry={noop}
        onBrowsePlans={noop}
        onOpenMyLine={noop}
        onOpenOrder={noop}
      />
    ),
  },
  'consumer-home-error': {
    label: 'Consumer Home — load error',
    render: () => <ConsumerHomeErrorTarget />,
  },

  /*
   * Chunk 19 (US-37). The three screens take their data as props and make no
   * calls of their own, so each target is the production component rendered
   * against a fixture — not a copy of it. The error states are registered
   * alongside the happy path deliberately: the chunk asks for checkout *and*
   * error-state evidence, and a payment screen is mostly its failures.
   */
  plans: {
    label: 'Plans — browse',
    render: () => (
      <PlanListScreen
        markets={[FIXTURE_MARKET]}
        market={FIXTURE_MARKET}
        products={[FIXTURE_PRODUCT]}
        device={FIXTURE_DEVICE_CHECKED}
        loading={false}
        errorMessage={null}
        busyProductId={null}
        onSelectMarket={noop}
        onChoose={noop}
        onConfirmEsimCapable={noop}
        onRetry={noop}
      />
    ),
  },
  'plans-device-unsupported': {
    label: 'Plans — device eSIM check failed',
    render: () => (
      <PlanListScreen
        markets={[FIXTURE_MARKET]}
        market={FIXTURE_MARKET}
        products={[FIXTURE_PRODUCT_DEVICE_BLOCKED]}
        device={FIXTURE_DEVICE_INCAPABLE}
        loading={false}
        errorMessage={null}
        busyProductId={null}
        onSelectMarket={noop}
        onChoose={noop}
        onConfirmEsimCapable={noop}
        onRetry={noop}
      />
    ),
  },
  'checkout-review': {
    label: 'Checkout — quote review',
    render: () => (
      <QuoteReviewScreen
        quote={FIXTURE_QUOTE}
        methods={FIXTURE_PAYMENT_METHODS}
        paying={false}
        errorMessage={null}
        quoteRejected={false}
        onPay={noop}
        onRequote={noop}
        onBack={noop}
      />
    ),
  },
  'checkout-collection-blocked': {
    label: 'Checkout — no live merchant account (D3/D4)',
    render: () => (
      <QuoteReviewScreen
        quote={FIXTURE_QUOTE}
        methods={FIXTURE_PAYMENT_METHODS_BLOCKED}
        paying={false}
        errorMessage={null}
        quoteRejected={false}
        onPay={noop}
        onRequote={noop}
        onBack={noop}
      />
    ),
  },
  'checkout-quote-expired': {
    label: 'Checkout — expired price',
    render: () => (
      <QuoteReviewScreen
        quote={FIXTURE_QUOTE}
        methods={FIXTURE_PAYMENT_METHODS}
        paying={false}
        errorMessage={null}
        quoteRejected
        onPay={noop}
        onRequote={noop}
        onBack={noop}
      />
    ),
  },
  'order-provisioning': {
    label: 'Order — paid, still being set up',
    render: () => (
      <OrderStatusScreen
        order={FIXTURE_ORDER}
        reference={FIXTURE_ORDER.reference}
        paymentStarted
        paymentHandoffFailed={false}
        loading={false}
        busy={false}
        errorMessage={null}
        onRefresh={noop}
        onResumePayment={noop}
        onOpenMyLine={noop}
        onBrowsePlans={noop}
        onDismiss={noop}
      />
    ),
  },
  'order-confirming-payment': {
    label: 'Order — confirming payment (webhook late)',
    render: () => (
      <OrderStatusScreen
        order={FIXTURE_ORDER_AWAITING_WEBHOOK}
        reference={FIXTURE_ORDER_AWAITING_WEBHOOK.reference}
        paymentStarted
        paymentHandoffFailed={false}
        loading={false}
        busy={false}
        errorMessage={null}
        onRefresh={noop}
        onResumePayment={noop}
        onOpenMyLine={noop}
        onBrowsePlans={noop}
        onDismiss={noop}
      />
    ),
  },
  'order-payment-declined': {
    label: 'Order — payment declined',
    render: () => (
      <OrderStatusScreen
        order={FIXTURE_ORDER_DECLINED}
        reference={FIXTURE_ORDER_DECLINED.reference}
        paymentStarted
        paymentHandoffFailed={false}
        loading={false}
        busy={false}
        errorMessage={null}
        onRefresh={noop}
        onResumePayment={noop}
        onOpenMyLine={noop}
        onBrowsePlans={noop}
        onDismiss={noop}
      />
    ),
  },
};
