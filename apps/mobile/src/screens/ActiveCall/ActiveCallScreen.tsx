import { Microphone, MicrophoneSlash, PhoneDisconnect, SpeakerHigh } from 'phosphor-react-native';
import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { useNetworkQuality, type NetworkQuality } from '../../hooks/useNetworkQuality';
import type { VoiceCallSession, VoiceCallState } from '../../services/voiceGateway';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

interface ActiveCallScreenProps {
  call: VoiceCallSession;
  recipientName?: string;
  onFinished: () => void;
  connectivityReturnDelayMs?: number;
  networkQualityOverride?: { connected: boolean; quality: NetworkQuality };
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  const remainder = (seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${remainder}`;
}

function QualityIndicator({ quality }: { quality: NetworkQuality }): React.JSX.Element {
  const levels: Record<NetworkQuality, number> = { poor: 1, fair: 2, good: 3, excellent: 4 };
  return (
    <View style={styles.qualityRow} accessibilityLabel={`Call quality ${quality}`} testID="call-quality">
      <View style={styles.signalBars}>
        {[1, 2, 3, 4].map((level) => (
          <View
            key={level}
            style={[
              styles.signalBar,
              { height: 5 + level * 4 },
              level <= levels[quality] ? styles.signalBarActive : styles.signalBarInactive,
            ]}
          />
        ))}
      </View>
      <Text style={styles.qualityLabel}>{quality[0].toUpperCase() + quality.slice(1)} quality</Text>
    </View>
  );
}

export function ActiveCallScreen({
  call,
  recipientName,
  onFinished,
  connectivityReturnDelayMs = 3000,
  networkQualityOverride,
}: ActiveCallScreenProps): React.JSX.Element {
  const liveNetwork = useNetworkQuality();
  const network = networkQualityOverride ?? liveNetwork;
  const [state, setState] = useState<VoiceCallState>('connecting');
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(false);
  const [connectivityLost, setConnectivityLost] = useState(false);

  useEffect(
    () =>
      call.subscribeState((nextState) => {
        setState(nextState);
        if (nextState === 'dropped') setConnectivityLost(true);
        if (nextState === 'ended') onFinished();
      }),
    [call, onFinished],
  );
  useEffect(() => call.subscribeDuration(setDuration), [call]);
  useEffect(() => {
    if (network.connected || connectivityLost) return;
    setConnectivityLost(true);
    call.hangup().catch(() => undefined);
  }, [call, connectivityLost, network.connected]);
  useEffect(() => {
    if (!connectivityLost) return;
    const timeout = setTimeout(onFinished, connectivityReturnDelayMs);
    return () => clearTimeout(timeout);
  }, [connectivityLost, connectivityReturnDelayMs, onFinished]);

  if (connectivityLost || state === 'dropped') {
    return (
      <View style={styles.screen}>
        <Banner tone="error" message="Call ended — connectivity lost" testID="connectivity-lost" />
        <Text style={styles.recipient}>{recipientName || call.displayNumber}</Text>
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <Text style={styles.eyebrow}>{state === 'connected' ? 'Connected' : 'Connecting…'}</Text>
      <Text style={styles.recipient}>{recipientName || call.displayNumber}</Text>
      {recipientName ? <Text style={styles.number}>{call.displayNumber}</Text> : null}
      <Text style={styles.duration}>{formatDuration(duration)}</Text>
      <View style={call.callType === 'app_to_app' ? styles.freePill : styles.standardPill}>
        <Text style={styles.typeLabel}>
          {call.callType === 'app_to_app' ? 'DamDam-to-DamDam — free' : 'Standard call'}
        </Text>
      </View>
      <QualityIndicator quality={network.quality} />

      <View style={styles.controls}>
        <CallControl
          label={muted ? 'Unmute' : 'Mute'}
          onPress={() => call.toggleMute().then(setMuted)}
          active={muted}
          icon={muted ? <MicrophoneSlash color={color.gray900} size={28} weight="bold" /> : <Microphone color={color.gray900} size={28} weight="bold" />}
        />
        <CallControl
          label="Speaker"
          onPress={() => call.toggleSpeaker().then(setSpeaker)}
          active={speaker}
          icon={<SpeakerHigh color={color.gray900} size={28} weight="bold" />}
        />
        <CallControl
          label="End call"
          onPress={() => call.hangup().finally(onFinished)}
          destructive
          icon={<PhoneDisconnect color={color.white} size={28} weight="fill" />}
        />
      </View>
    </View>
  );
}

function CallControl({
  label,
  onPress,
  icon,
  active = false,
  destructive = false,
}: {
  label: string;
  onPress: () => void;
  icon: React.JSX.Element;
  active?: boolean;
  destructive?: boolean;
}): React.JSX.Element {
  return (
    <View style={styles.controlWrap}>
      <Pressable
        accessibilityLabel={label}
        onPress={onPress}
        style={[
          styles.controlButton,
          active && styles.controlActive,
          destructive && styles.controlDestructive,
        ]}
      >
        {icon}
      </Pressable>
      <Text style={styles.controlLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingVertical: space.space8,
    alignItems: 'center',
    gap: space.space3,
  },
  eyebrow: { ...typography.body, color: color.gray600 },
  recipient: { ...typography.heading1, textAlign: 'center', color: color.gray900 },
  number: { ...typography.bodyLarge, color: color.gray600 },
  duration: { ...typography.numeral, color: color.gray900, marginVertical: space.space3 },
  freePill: { borderRadius: radius.card, backgroundColor: color.success100, paddingHorizontal: space.space3, paddingVertical: space.space2 },
  standardPill: { borderRadius: radius.card, backgroundColor: color.gray100, paddingHorizontal: space.space3, paddingVertical: space.space2 },
  typeLabel: { ...typography.caption, fontWeight: '600', color: color.gray900 },
  qualityRow: { flexDirection: 'row', alignItems: 'center', gap: space.space2, marginTop: space.space4 },
  signalBars: { height: 24, flexDirection: 'row', alignItems: 'flex-end', gap: space.space1 },
  signalBar: { width: 5, borderRadius: 2 },
  signalBarActive: { backgroundColor: color.success700 },
  signalBarInactive: { backgroundColor: color.gray300 },
  qualityLabel: { ...typography.caption, color: color.gray700 },
  controls: { marginTop: 'auto', flexDirection: 'row', justifyContent: 'space-around', width: '100%', paddingBottom: space.space8 },
  controlWrap: { alignItems: 'center', gap: space.space2, width: 88 },
  controlButton: { width: 64, height: 64, borderRadius: 32, backgroundColor: color.white, borderWidth: 1, borderColor: color.gray200, alignItems: 'center', justifyContent: 'center' },
  controlActive: { backgroundColor: color.primary100, borderColor: color.primary500 },
  controlDestructive: { backgroundColor: color.error700, borderColor: color.error700 },
  controlLabel: { ...typography.caption, color: color.gray700, minHeight: minTouchTarget - 20, textAlign: 'center' },
});
