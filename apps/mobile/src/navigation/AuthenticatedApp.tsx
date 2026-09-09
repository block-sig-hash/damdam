import DeviceInfo from 'react-native-device-info';
import React, { useEffect, useState } from 'react';
import { getEsim, type EsimProfile } from '../api/esimClient';
import { EsimActivationFlow } from '../screens/EsimActivation/EsimActivationFlow';
import { EsimQrCodeScreen } from '../screens/EsimSetup/EsimQrCodeScreen';
import { HomeDashboardScreen } from '../screens/HomeDashboard/HomeDashboardScreen';
import {useHomePackageStatus} from '../screens/HomeDashboard/useHomePackageStatus';
import {registerPushInstallation, subscribeToActivationDeepLinks} from '../services/activationLinks';
import type { AuthenticatedMobileSession } from './OnboardingNavigator';

type AuthenticatedAppProps = Pick<
  AuthenticatedMobileSession,
  'accessToken' | 'departureDate' | 'packageId'
>;

type Screen = 'home' | 'activation' | 'qr';

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
  const {balances} = useHomePackageStatus(accessToken, packageId);
  useEffect(() => {
    registerPushInstallation(accessToken).catch(() => undefined);
    return subscribeToActivationDeepLinks((linkedPackageId) => {
      setPackageId(linkedPackageId);
      setScreen('activation');
    });
  }, [accessToken]);

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
  return (
    <HomeDashboardScreen
      departureDate={departureDate}
      esimStatus={esimStatus}
      remainingDataGb={balances?.remainingDataGb ?? null}
      dataTotalGb={balances?.dataTotalGb ?? null}
      pstnMinutesRemaining={balances?.pstnMinutesRemaining ?? null}
      pstnMinutesTotal={balances?.pstnMinutesTotal ?? null}
      onActivateEsim={() => packageId && setScreen('activation')}
    />
  );
}
