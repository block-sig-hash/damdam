import DeviceInfo from 'react-native-device-info';
import React, { useEffect, useState } from 'react';
import { getEsim, type EsimProfile } from '../api/esimClient';
import { getPackageStatus } from '../api/paymentClient';
import { EsimActivationFlow } from '../screens/EsimActivation/EsimActivationFlow';
import { EsimQrCodeScreen } from '../screens/EsimSetup/EsimQrCodeScreen';
import { HomeDashboardScreen } from '../screens/HomeDashboard/HomeDashboardScreen';
import {
  optIntoArrivalGeofence,
  registerPushInstallation,
  subscribeToActivationDeepLinks,
} from '../services/arrivalPrompts';
import type { AuthenticatedMobileSession } from './OnboardingNavigator';

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
}: AuthenticatedMobileSession): React.JSX.Element {
  const [screen, setScreen] = useState<Screen>('home');
  const [packageId, setPackageId] = useState(initialPackageId);
  const [esimStatus, setEsimStatus] = useState<
    EsimProfile['status'] | 'not_issued'
  >('not_issued');
  const [remainingDataGb, setRemainingDataGb] = useState(0);

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
    getPackageStatus(accessToken, packageId)
      .then((status) => active && setRemainingDataGb(status.data_gb_remaining))
      .catch(() => undefined);
    // The OS permission prompts are the opt-in gate. A denial never affects the
    // permission-free date banner, and registration can be offered again later.
    optIntoArrivalGeofence(packageId).catch(() => undefined);
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
      remainingDataGb={remainingDataGb}
      onActivateEsim={() => packageId && setScreen('activation')}
    />
  );
}
