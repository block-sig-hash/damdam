import DeviceInfo from 'react-native-device-info';
import NetInfo, {
  NetInfoStateType,
  type NetInfoState,
} from '@react-native-community/netinfo';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {getRecentCheckIns, sendCheckIn} from '../api/checkInClient';
import { getEsim, type EsimProfile } from '../api/esimClient';
import { EsimActivationFlow } from '../screens/EsimActivation/EsimActivationFlow';
import { EsimQrCodeScreen } from '../screens/EsimSetup/EsimQrCodeScreen';
import { HomeDashboardScreen } from '../screens/HomeDashboard/HomeDashboardScreen';
import {useHomePackageStatus} from '../screens/HomeDashboard/useHomePackageStatus';
import { ActiveCallScreen } from '../screens/ActiveCall/ActiveCallScreen';
import { DialPadScreen } from '../screens/DialPad/DialPadScreen';
import type { VoiceCallSession } from '../services/voiceGateway';
import {configureCheckInBackgroundSync} from '../services/checkInBackground';
import {optionalCheckInLocation} from '../services/checkInLocation';
import {CheckInSyncService, NitroCheckInOutbox} from '../services/checkInOutbox';
import {sendSOS, cancelSOS, type SOSResponse} from '../api/sosClient';
import {NitroSOSOutbox, SOSSyncService, type SOSOutboxItem} from '../services/sosOutbox';
import {SosConfirmScreen} from '../screens/SosConfirm/SosConfirmScreen';
import {SosSentScreen} from '../screens/SosSent/SosSentScreen';
import {getEmergencyContact} from '../api/emergencyContactClient';
import {
  optIntoArrivalGeofence,
  registerPushInstallation,
  subscribeToActivationDeepLinks,
} from '../services/arrivalPrompts';
import type { AuthenticatedMobileSession } from './OnboardingNavigator';

type Screen = 'home' | 'activation' | 'qr' | 'dial' | 'active-call' | 'sos-confirm' | 'sos-sent';

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
  const [activeCall, setActiveCall] = useState<VoiceCallSession>();
  const [recipientName, setRecipientName] = useState<string>();
  const [balanceRefreshBaseline, setBalanceRefreshBaseline] = useState<number>();
  const [queuedCheckIns, setQueuedCheckIns] = useState(0);
  const [lastCheckInAt, setLastCheckInAt] = useState<string | null>(null);
  const [queuedSOS, setQueuedSOS] = useState<SOSOutboxItem>();
  const [queuedSOSCount, setQueuedSOSCount] = useState(0);
  const [sosServerId, setSosServerId] = useState<string>();
  const [sosSynced, setSosSynced] = useState(false);
  const [htoPhone, setHtoPhone] = useState('');
  const cancelRequested = useRef(false);
  const networkState = useRef<NetInfoState>({
    type: NetInfoStateType.unknown,
    isConnected: false,
    isInternetReachable: null,
    details: null,
  });
  const {balances, refresh: refreshPackageStatus} = useHomePackageStatus(
    accessToken,
    packageId,
  );
  const pstnMinutesRemaining = balances?.pstnMinutesRemaining ?? 0;
  const checkIns = useMemo(
    () =>
      new CheckInSyncService(
        new NitroCheckInOutbox(),
        item => sendCheckIn(accessToken, item),
        pending => setQueuedCheckIns(pending.length),
      ),
    [accessToken],
  );
  const sos = useMemo(
    () => new SOSSyncService(
      new NitroSOSOutbox(),
      item => sendSOS(accessToken, item),
      rows => {
        setQueuedSOSCount(rows.length);
        if (rows[0]) setQueuedSOS(rows[0]);
      },
      (_item, response) => {
        const result = response as SOSResponse;
        setSosServerId(result.id);
        setSosSynced(true);
        if (cancelRequested.current) {
          cancelSOS(accessToken, result.id).then(() => {
            cancelRequested.current = false;
            setQueuedSOS(undefined);
            setQueuedSOSCount(0);
            setSosServerId(undefined);
            setScreen('home');
          }).catch(() => undefined);
        }
      },
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
    configureCheckInBackgroundSync(checkIns, sos)
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
  }, [accessToken, checkIns, sos]);

  useEffect(() => {
    let active = true;
    let stop: () => void = () => undefined;
    sos.initialize().then(rows => {
      if (!active) return;
      if (rows[0]) {
        setQueuedSOS(rows[0]);
        setScreen('sos-sent');
      }
      stop = sos.start(() => networkState.current);
    }).catch(() => undefined);
    const unsubscribe = NetInfo.addEventListener(state => {
      networkState.current = state;
      sos.connectivityChanged(state).catch(() => undefined);
    });
    getEmergencyContact(accessToken).then(contact => {
      if (active) setHtoPhone(contact.hto_operator_phone_number ?? '');
    }).catch(() => undefined);
    return () => { active = false; stop(); unsubscribe(); };
  }, [accessToken, sos]);

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
        onCallStarted={(call, name) => {
          setActiveCall(call);
          setRecipientName(name);
          setScreen('active-call');
        }}
      />
    );
  }
  if (screen === 'sos-confirm') {
    return <SosConfirmScreen onConfirmed={async () => {
      const item = await sos.captureOnce(undefined, new Date(), true);
      setQueuedSOS(item);
      setSosSynced(false);
      setScreen('sos-sent');
      try {
        const location = await optionalCheckInLocation();
        if (location) await sos.enrichLocation(item.clientGeneratedId, location);
      } finally {
        sos.releaseEnrichment(item.clientGeneratedId);
      }
      const current = await NetInfo.fetch();
      networkState.current = current;
      await sos.sync(current);
    }} />;
  }
  if (screen === 'sos-sent' && queuedSOS) {
    return <SosSentScreen
      synced={sosSynced}
      htoPhone={htoPhone}
      timestamp={queuedSOS.timestamp}
      onCancel={() => {
        if (!sosServerId) {
          cancelRequested.current = true;
          return;
        }
        cancelSOS(accessToken, sosServerId)
          .then(() => {
            setQueuedSOS(undefined);
            setQueuedSOSCount(0);
            setSosServerId(undefined);
            setScreen('home');
          })
          .catch(() => undefined);
      }}
    />;
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
      onOpenSOS={() => setScreen('sos-confirm')}
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
      queuedSOSAlerts={queuedSOSCount}
    />
  );
}
