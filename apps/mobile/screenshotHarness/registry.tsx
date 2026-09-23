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
import { MyLineScreen } from '../src/screens/MyLine/MyLineScreen';
import { InstallProfileScreen } from '../src/screens/MyLine/InstallProfileScreen';
import { CallingGuideScreen } from '../src/screens/MyLine/CallingGuideScreen';
import { CallsScreen } from '../src/screens/Calls/CallsScreen';
import { AccountScreen } from '../src/screens/Account/AccountScreen';
import { ReceiptsScreen } from '../src/screens/Account/ReceiptsScreen';
import { activationGuideFor } from '../src/screens/EsimActivation/activationGuides';
import { savePinLocally } from '../src/utils/pinLocalStore';
import {
  FIXTURE_ACCESS_TOKEN,
  FIXTURE_CALL_ACTIVE,
  FIXTURE_CALL_ELIGIBILITY,
  FIXTURE_CALL_HISTORY,
  FIXTURE_CALL_IDLE,
  FIXTURE_DEVICE_CHECKED,
  FIXTURE_INSTALLATION_CREDENTIAL,
  FIXTURE_LINE,
  FIXTURE_LINE_AWAITING_ACTIVATION,
  FIXTURE_LINE_SUSPENDED,
  FIXTURE_LINE_UNMEASURED,
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
  createActiveFixtureQuote,
} from './fixtures';

const noop = () => undefined;

/**
 * PinUnlockScreen's stage depends on react-native-keychain state that's
 * read asynchronously on mount -- seed a fixture PIN first so the
 * screen resolves to its normal digit-entry state ('entry') rather
 * than 'no-local-pin' (a fresh install has no locally-stored PIN).
 */
const FIXTURE_USER_ID = 'fixture-0000-4000-8000-000000000001';
const FIXTURE_RECEIPT = {
  order_id: 'fixture-order-1',
  reference: 'FIXTURE-ORDER-1',
  placed_at: '2026-09-01T09:00:00Z',
  currency: 'NGN',
  total_amount: '5000.000000',
  payment_state: 'paid',
  lines: [{
    description: 'Example connectivity plan',
    quantity: 1,
    unit_amount: '5000.000000',
    total_amount: '5000.000000',
  }],
  organization_id: null,
};

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
  home: {
    label: 'Consumer Home — provisioned service',
    render: () => (
      <ConsumerHomeScreen
        serviceState="active"
        services={[{
          order_item_id: 'fixture-item-1',
          entitlement_id: 'fixture-entitlement-1',
          order_id: 'fixture-order-1',
          order_reference: 'FIXTURE-ORDER-1',
          product_name: 'Example connectivity plan',
          delivery: 'carrier_esim',
          owner: 'personal',
          organization_id: null,
          organization_name: null,
          payment_state: 'paid',
          provisioning_state: 'provisioned',
          installation_state: 'installed',
          activation_state: 'active',
          requires_installation: true,
          ready_to_use: true,
          granted_at: '2026-09-01T09:00:00Z',
          expires_at: '2026-10-01T09:00:00Z',
          expired: false,
        }]}
        loading={false}
        errorMessage={null}
        onRetry={noop}
        onBrowsePlans={noop}
        onOpenMyLine={noop}
        onOpenOrder={noop}
      />
    ),
  },
  account: {
    label: 'Account — profile and actions',
    render: () => (
      <AccountScreen
        displayName="Fixture Holder"
        phoneNumber={null}
        email="holder@example.test"
        sessions={[]}
        receipts={[FIXTURE_RECEIPT]}
        supportRequests={[]}
        observedAt="2026-09-01T09:00:00Z"
        offline={false}
        onOpenDevices={noop}
        onOpenReceipts={noop}
        onOpenSupport={noop}
        onOpenNotifications={noop}
        onOpenPrivacy={noop}
      />
    ),
  },
  receipts: {
    label: 'Account — receipts',
    render: () => (
      <ReceiptsScreen receipts={[FIXTURE_RECEIPT]} fromCache={false} onBack={noop} />
    ),
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
        quote={createActiveFixtureQuote()}
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
        quote={createActiveFixtureQuote()}
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

  /*
   * Chunk 20 (US-38). The installation target is captured with its screen
   * protection reported as *unavailable*, which is the honest worst case and the
   * one whose copy matters most — on iOS there is no way to block a screenshot,
   * and the warning is the whole mitigation. The activation code in the fixture
   * is deliberately unusable (`harness.invalid`).
   */
  'my-line': {
    label: 'My Line — working',
    render: () => (
      <MyLineScreen
        line={FIXTURE_LINE}
        loading={false}
        errorMessage={null}
        onRefresh={noop}
        onInstall={noop}
        onOpenCallingGuide={noop}
        onBrowsePlans={noop}
      />
    ),
  },
  'my-line-awaiting-activation': {
    label: 'My Line — installed, waiting for the network',
    render: () => (
      <MyLineScreen
        line={FIXTURE_LINE_AWAITING_ACTIVATION}
        loading={false}
        errorMessage={null}
        onRefresh={noop}
        onInstall={noop}
        onOpenCallingGuide={noop}
        onBrowsePlans={noop}
      />
    ),
  },
  'my-line-suspended': {
    label: 'My Line — suspended',
    render: () => (
      <MyLineScreen
        line={FIXTURE_LINE_SUSPENDED}
        loading={false}
        errorMessage={null}
        onRefresh={noop}
        onInstall={noop}
        onOpenCallingGuide={noop}
        onBrowsePlans={noop}
      />
    ),
  },
  'my-line-usage-unmeasured': {
    label: 'My Line — no usage ever reported',
    render: () => (
      <MyLineScreen
        line={FIXTURE_LINE_UNMEASURED}
        loading={false}
        errorMessage={null}
        onRefresh={noop}
        onInstall={noop}
        onOpenCallingGuide={noop}
        onBrowsePlans={noop}
      />
    ),
  },
  'my-line-installation': {
    label: 'My Line — activation code (screenshots unprotected)',
    render: () => (
      <InstallProfileScreen
        credential={FIXTURE_INSTALLATION_CREDENTIAL}
        guide={activationGuideFor('android', 'Tecno Camon 20')}
        privacy="unsupported"
        loading={false}
        busy={false}
        errorMessage={null}
        directInstallInvoked={false}
        onReveal={noop}
        onDirectInstall={noop}
        onConfirmInstalled={noop}
        onReportFailed={noop}
        onBack={noop}
      />
    ),
  },
  'my-line-calling-guide': {
    label: 'My Line — choosing this line for calls',
    render: () => <CallingGuideScreen line={FIXTURE_LINE} onBack={noop} />,
  },

  /*
   * Chunk V04 (US-47). Three states of the internet-calling surface.
   *
   * `call-active` is captured with `backgroundCall: false`, which is the honest
   * setting today and the one whose copy matters: no adapter has proven audio
   * survives the app going to background, and the disclosure is the whole
   * mitigation. `call-history` deliberately includes a call whose cost is still
   * being worked out and one nobody answered, because "no charge yet" and "no
   * charge" have to look different from each other.
   */
  'call-setup': {
    label: 'Calls — before dialling',
    render: () => (
      <CallsScreen
        destination="+441632960011"
        onDestinationChange={noop}
        payers={[{ id: null, label: 'Personal' }]}
        selectedPayerId={null}
        onSelectPayer={noop}
        eligibility={FIXTURE_CALL_ELIGIBILITY}
        eligibilityLoading={false}
        eligibilityError={null}
        snapshot={FIXTURE_CALL_IDLE}
        history={[]}
        historyLoading={false}
        historyError={null}
        onCall={noop}
        onHangUp={noop}
        onToggleMute={noop}
        onDigit={noop}
        onToggleSpeaker={noop}
        onDismissFailure={noop}
        onRetry={noop}
      />
    ),
  },
  'call-active': {
    label: 'Calls — answered, on the call',
    render: () => (
      <CallsScreen
        destination="+441632960011"
        onDestinationChange={noop}
        payers={[{ id: null, label: 'Personal' }]}
        selectedPayerId={null}
        onSelectPayer={noop}
        eligibility={FIXTURE_CALL_ELIGIBILITY}
        eligibilityLoading={false}
        eligibilityError={null}
        snapshot={FIXTURE_CALL_ACTIVE}
        history={[]}
        historyLoading={false}
        historyError={null}
        onCall={noop}
        onHangUp={noop}
        onToggleMute={noop}
        onDigit={noop}
        onToggleSpeaker={noop}
        onDismissFailure={noop}
        onRetry={noop}
      />
    ),
  },
  'call-history': {
    label: 'Calls — recent calls and what they cost',
    render: () => (
      <CallsScreen
        destination=""
        onDestinationChange={noop}
        payers={[{ id: null, label: 'Personal' }]}
        selectedPayerId={null}
        onSelectPayer={noop}
        eligibility={null}
        eligibilityLoading={false}
        eligibilityError={null}
        snapshot={FIXTURE_CALL_IDLE}
        history={FIXTURE_CALL_HISTORY}
        historyLoading={false}
        historyError={null}
        onCall={noop}
        onHangUp={noop}
        onToggleMute={noop}
        onDigit={noop}
        onToggleSpeaker={noop}
        onDismissFailure={noop}
        onRetry={noop}
      />
    ),
  },
};
