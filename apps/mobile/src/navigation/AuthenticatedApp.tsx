import DeviceInfo from 'react-native-device-info';
import React, { useEffect, useMemo, useState } from 'react';
import { getEsim, type EsimProfile } from '../api/esimClient';
import { EsimActivationFlow } from '../screens/EsimActivation/EsimActivationFlow';
import { EsimQrCodeScreen } from '../screens/EsimSetup/EsimQrCodeScreen';
import { HomeDashboardScreen } from '../screens/HomeDashboard/HomeDashboardScreen';
import {useHomePackageStatus} from '../screens/HomeDashboard/useHomePackageStatus';
import { ActiveCallScreen } from '../screens/ActiveCall/ActiveCallScreen';
import { DialPadScreen } from '../screens/DialPad/DialPadScreen';
import { CliManageScreen } from '../screens/CliVerification/CliManageScreen';
import { CliVerifyEntryScreen } from '../screens/CliVerification/CliVerifyEntryScreen';
import { CliVerifyConfirmScreen } from '../screens/CliVerification/CliVerifyConfirmScreen';
import { CliConsentScreen } from '../screens/CliVerification/CliConsentScreen';
import type { VerifiedCallerIdentity } from '../api/cliClient';
import type { VoiceCallSession } from '../services/voiceGateway';
import { createCallKitVoiceGateway, initializeCallKit } from '../services/callKit';
import {registerPushInstallation, subscribeToActivationDeepLinks} from '../services/activationLinks';
import type { AuthenticatedMobileSession } from './OnboardingNavigator';

type AuthenticatedAppProps = Pick<
  AuthenticatedMobileSession,
  'accessToken' | 'departureDate' | 'packageId'
>;

type Screen =
  | 'home'
  | 'activation'
  | 'qr'
  | 'dial'
  | 'active-call'
  | 'cli-manage'
  | 'cli-verify-entry'
  | 'cli-verify-confirm'
  | 'cli-consent';

/**
 * The smallest authenticated host for the eSIM stories. It deliberately leaves
 * the Claude-owned onboarding screens untouched and connects their completed
 * session to Home, arrival registration, deep links, activation, and QR fallback.
 */
export function AuthenticatedApp({
  accessToken,
  departureDate,
  packageId: initialPackageId,
}: AuthenticatedAppProps): React.JSX.Element {
  const [screen, setScreen] = useState<Screen>('home');
  const [packageId, setPackageId] = useState(initialPackageId);
  const [esimStatus, setEsimStatus] = useState<
    EsimProfile['status'] | 'not_issued'
  >('not_issued');
  const [activeCall, setActiveCall] = useState<VoiceCallSession>();
  const [recipientName, setRecipientName] = useState<string>();
  const [balanceRefreshBaseline, setBalanceRefreshBaseline] = useState<number>();
  const [cliIdentity, setCliIdentity] = useState<VerifiedCallerIdentity>();
  const {balances, refresh: refreshPackageStatus} = useHomePackageStatus(
    accessToken,
    packageId,
  );
  const pstnMinutesRemaining = balances?.pstnMinutesRemaining ?? 0;
  // iOS only (frontend-mobile.md §8.3); createCallKitVoiceGateway returns
  // the unmodified default gateway on Android, so this has no effect there.
  const voiceGateway = useMemo(() => createCallKitVoiceGateway(), []);

  useEffect(() => {
    registerPushInstallation(accessToken).catch(() => undefined);
    return subscribeToActivationDeepLinks((linkedPackageId) => {
      setPackageId(linkedPackageId);
      setScreen('activation');
    });
  }, [accessToken]);

  useEffect(
    () =>
      initializeCallKit(accessToken, {
        onIncomingCallReady: (session) => {
          setActiveCall(session);
          setRecipientName(session.displayNumber);
          setScreen('active-call');
        },
      }),
    [accessToken],
  );

  useEffect(() => {
    if (!packageId) return;
    let active = true;
    getEsim(accessToken, packageId)
      .then((profile) => active && setEsimStatus(profile.status))
      .catch(() => active && setEsimStatus('not_issued'));
    return () => {
      active = false;
    };
  }, [accessToken, packageId]);

  useEffect(() => {
    if (balanceRefreshBaseline === undefined || !packageId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const deadline = Date.now() + 60_000;
    const refresh = async (): Promise<void> => {
      try {
        const status = await refreshPackageStatus();
        if (!active) return;
        if (
          status &&
          status.pstnMinutesRemaining < balanceRefreshBaseline
        ) {
          setBalanceRefreshBaseline(undefined);
          return;
        }
      } catch {
        // A transient refresh failure must not interrupt the completed call flow.
      }
      if (active && Date.now() < deadline) timer = setTimeout(refresh, 5000);
      else if (active) setBalanceRefreshBaseline(undefined);
    };
    refresh().catch(() => undefined);
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [balanceRefreshBaseline, packageId, refreshPackageStatus]);

  if (screen === 'qr' && packageId) {
    return <EsimQrCodeScreen accessToken={accessToken} packageId={packageId} />;
  }
  if (screen === 'activation' && packageId) {
    return (
      <EsimActivationFlow
        accessToken={accessToken}
        packageId={packageId}
        deviceModel={DeviceInfo.getModel()}
        onShowQrCode={() => setScreen('qr')}
        onActivated={() => {
          setEsimStatus('activated');
          setScreen('home');
        }}
      />
    );
  }
  if (screen === 'active-call' && activeCall) {
    return (
      <ActiveCallScreen
        call={activeCall}
        recipientName={recipientName}
        onFinished={() => {
          if (activeCall.callType === 'pstn') {
            setBalanceRefreshBaseline(pstnMinutesRemaining);
          }
          setActiveCall(undefined);
          setRecipientName(undefined);
          setScreen('dial');
        }}
      />
    );
  }
  if (screen === 'dial') {
    return (
      <DialPadScreen
        accessToken={accessToken}
        pstnMinutesRemaining={pstnMinutesRemaining}
        voiceGateway={voiceGateway}
        onCallStarted={(call, name) => {
          setActiveCall(call);
          setRecipientName(name);
          setScreen('active-call');
        }}
        onManageCli={() => setScreen('cli-manage')}
      />
    );
  }
  if (screen === 'cli-manage') {
    return (
      <CliManageScreen
        accessToken={accessToken}
        onVerifyNumber={() => setScreen('cli-verify-entry')}
        onResumeConfirm={(identity) => {
          setCliIdentity(identity);
          setScreen('cli-verify-confirm');
        }}
        onResumeConsent={(identity) => {
          setCliIdentity(identity);
          setScreen('cli-consent');
        }}
      />
    );
  }
  if (screen === 'cli-verify-entry') {
    return (
      <CliVerifyEntryScreen
        accessToken={accessToken}
        onStarted={(identity) => {
          setCliIdentity(identity);
          setScreen('cli-verify-confirm');
        }}
        onCancel={() => setScreen('cli-manage')}
      />
    );
  }
  if (screen === 'cli-verify-confirm' && cliIdentity) {
    return (
      <CliVerifyConfirmScreen
        accessToken={accessToken}
        identityId={cliIdentity.id}
        phoneNumber={cliIdentity.phone_number}
        onConfirmed={(identity) => {
          setCliIdentity(identity);
          setScreen('cli-consent');
        }}
        onUseDifferentNumber={() => setScreen('cli-verify-entry')}
      />
    );
  }
  if (screen === 'cli-consent' && cliIdentity) {
    return (
      <CliConsentScreen
        accessToken={accessToken}
        identityId={cliIdentity.id}
        phoneNumber={cliIdentity.phone_number}
        onConsented={() => {
          setCliIdentity(undefined);
          setScreen('dial');
        }}
      />
    );
  }
  return (
    <HomeDashboardScreen
      departureDate={departureDate}
      esimStatus={esimStatus}
      remainingDataGb={balances?.remainingDataGb ?? null}
      dataTotalGb={balances?.dataTotalGb ?? null}
      pstnMinutesRemaining={balances?.pstnMinutesRemaining ?? null}
      pstnMinutesTotal={balances?.pstnMinutesTotal ?? null}
      onActivateEsim={() => packageId && setScreen('activation')}
      onOpenCall={() => setScreen('dial')}
    />
  );
}
