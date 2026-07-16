import DeviceInfo from 'react-native-device-info';
import NetInfo, {
  NetInfoStateType,
  type NetInfoState,
} from '@react-native-community/netinfo';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {getRecentCheckIns, sendCheckIn} from '../api/checkInClient';
import { getEsim, type EsimProfile } from '../api/esimClient';
import { getPackageStatus } from '../api/paymentClient';
import { EsimActivationFlow } from '../screens/EsimActivation/EsimActivationFlow';
import { EsimQrCodeScreen } from '../screens/EsimSetup/EsimQrCodeScreen';
import { HomeDashboardScreen } from '../screens/HomeDashboard/HomeDashboardScreen';
import { ActiveCallScreen } from '../screens/ActiveCall/ActiveCallScreen';
import { DialPadScreen } from '../screens/DialPad/DialPadScreen';
import type { VoiceCallSession } from '../services/voiceGateway';
import {configureCheckInBackgroundSync} from '../services/checkInBackground';
import {optionalCheckInLocation} from '../services/checkInLocation';
import {CheckInSyncService, NitroCheckInOutbox} from '../services/checkInOutbox';
import {
  optIntoArrivalGeofence,
  registerPushInstallation,
  subscribeToActivationDeepLinks,
} from '../services/arrivalPrompts';
import type { AuthenticatedMobileSession } from './OnboardingNavigator';

type Screen = 'home' | 'activation' | 'qr' | 'dial' | 'active-call';

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
  const [pstnMinutesRemaining, setPstnMinutesRemaining] = useState(0);
  const [activeCall, setActiveCall] = useState<VoiceCallSession>();
  const [recipientName, setRecipientName] = useState<string>();
  const [balanceRefreshBaseline, setBalanceRefreshBaseline] = useState<number>();
  const [queuedCheckIns, setQueuedCheckIns] = useState(0);
  const [lastCheckInAt, setLastCheckInAt] = useState<string | null>(null);
  const networkState = useRef<NetInfoState>({
    type: NetInfoStateType.unknown,
    isConnected: false,
    isInternetReachable: null,
    details: null,
  });
  const checkIns = useMemo(
    () =>
      new CheckInSyncService(
        new NitroCheckInOutbox(),
        item => sendCheckIn(accessToken, item),
        pending => setQueuedCheckIns(pending.length),
      ),
    [accessToken],
  );

  useEffect(() => {
    let active = true;
    let stopTimer: () => void = () => undefined;
    let stopBackground: () => void = () => undefined;
    checkIns.initialize().then(rows => {
      if (!active) return;
      if (rows.length) setLastCheckInAt(rows[rows.length - 1].timestamp);
      stopTimer = checkIns.start(() => networkState.current);
    }).catch(() => undefined);
    getRecentCheckIns(accessToken)
      .then(rows => active && rows.length && setLastCheckInAt(rows[0].timestamp))
      .catch(() => undefined);
    const unsubscribe = NetInfo.addEventListener(state => {
      networkState.current = state;
      checkIns.connectivityChanged(state).catch(() => undefined);
    });
    configureCheckInBackgroundSync(checkIns)
      .then(stop => {
        if (active) stopBackground = stop;
        else stop();
      })
      .catch(() => undefined);
    return () => {
      active = false;
      unsubscribe();
      stopTimer();
      stopBackground();
    };
  }, [accessToken, checkIns]);

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
      .then((status) => {
        if (!active) return;
        setRemainingDataGb(status.data_gb_remaining);
        setPstnMinutesRemaining(status.pstn_minutes_remaining);
      })
      .catch(() => undefined);
    // The OS permission prompts are the opt-in gate. A denial never affects the
    // permission-free date banner, and registration can be offered again later.
    optIntoArrivalGeofence(packageId).catch(() => undefined);
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
        const status = await getPackageStatus(accessToken, packageId);
        if (!active) return;
        setPstnMinutesRemaining(status.pstn_minutes_remaining);
        if (status.pstn_minutes_remaining < balanceRefreshBaseline) {
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
  }, [accessToken, balanceRefreshBaseline, packageId]);

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
        onCallStarted={(call, name) => {
          setActiveCall(call);
          setRecipientName(name);
          setScreen('active-call');
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
      onOpenCall={() => setScreen('dial')}
      onCheckIn={async () => {
        const tappedAt = new Date();
        const item = await checkIns.capture(undefined, tappedAt, true);
        setLastCheckInAt(item.timestamp);
        try {
          const location = await optionalCheckInLocation();
          if (location) {
            await checkIns.enrichLocation(item.clientGeneratedId, location);
          }
        } finally {
          checkIns.releaseEnrichment(item.clientGeneratedId);
        }
        const current = await NetInfo.fetch();
        networkState.current = current;
        await checkIns.sync(current);
        return (await checkIns.isPending(item.clientGeneratedId)) ? 'queued' : 'sent';
      }}
      lastCheckInAt={lastCheckInAt}
      queuedCheckIns={queuedCheckIns}
    />
  );
}
