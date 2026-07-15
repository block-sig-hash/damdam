import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Platform, StyleSheet, Text, View } from 'react-native';
import { getEsim } from '../../api/esimClient';
import {
  activateAndConfirmAndroidProfile,
  confirmActivatedAfterConnectivity,
  getActivationPath,
  runSingleFlight,
  type ActivationPath,
} from '../../services/esimActivation';
import { color, space, typography } from '../../theme/tokens';
import { EsimActivationGuideScreen } from './EsimActivationGuideScreen';
import { EsimActivationPromptScreen } from './EsimActivationPromptScreen';

interface Props {
  accessToken: string;
  packageId: string;
  deviceModel: string;
  onShowQrCode: () => void;
  onActivated: () => void;
}

export function EsimActivationFlow({
  accessToken, packageId, deviceModel, onShowQrCode, onActivated,
}: Props): React.JSX.Element {
  const [path, setPath] = useState<ActivationPath>('manual');
  const [iccid, setIccid] = useState<string>();
  const [showGuide, setShowGuide] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string>();
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    getEsim(accessToken, packageId).then(async profile => {
      const nextPath = await getActivationPath(profile.iccid);
      if (!active) return;
      setIccid(profile.iccid);
      setPath(nextPath);
      if (profile.status === 'activated') onActivated();
    }).catch(() => active && setError('Your eSIM details could not load. Please try again.'));
    return () => { active = false; };
  }, [accessToken, onActivated, packageId]);

  const runOnce = useCallback(async (
    action: () => Promise<'activated' | 'not_connected'>,
  ) => {
    await runSingleFlight(inFlight, async () => {
      setWorking(true);
      setError(undefined);
      try {
        const result = await action();
        if (result === 'activated') onActivated();
        else setError('DamDam could not confirm mobile data yet. Check your eSIM is selected, then try again.');
      } catch {
        setError('Activation could not complete. Use the manual guide instead.');
        setShowGuide(true);
      } finally {
        setWorking(false);
      }
    });
  }, [onActivated]);

  if (!iccid && !error) {
    return <View style={styles.loading}><ActivityIndicator color={color.primary500} /></View>;
  }
  if (showGuide || path === 'manual') {
    return <View style={styles.fill}>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <EsimActivationGuideScreen
        platform={Platform.OS === 'ios' ? 'ios' : 'android'}
        deviceModel={deviceModel}
        onShowQrCode={onShowQrCode}
        onConfirmActivated={() => runOnce(() =>
          confirmActivatedAfterConnectivity(accessToken, packageId))}
        confirming={working}
      />
    </View>;
  }
  return <View style={styles.fill}>
    {error ? <Text style={styles.error}>{error}</Text> : null}
    <EsimActivationPromptScreen
      activationPath={path}
      onActivate={() => runOnce(() =>
        activateAndConfirmAndroidProfile(accessToken, packageId, iccid!))}
      onManualGuide={() => setShowGuide(true)}
      activating={working}
    />
  </View>;
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: color.gray50 },
  loading: {
    flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: color.gray50,
  },
  error: {
    ...typography.body, color: color.error700, backgroundColor: color.error100, padding: space.space4,
  },
});
