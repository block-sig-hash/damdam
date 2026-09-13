import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { useElapsedSeconds } from '../../hooks/useElapsedSeconds';
import type { CallSnapshot } from '../../services/calling/callSession';
import { Keypad } from './Keypad';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

/**
 * The call itself, while it is happening (US-47, chunk V04).
 *
 * Three decisions here are about honesty rather than layout.
 *
 * **The timer starts at answer and says it is an estimate.** Ringing is not
 * billable, so a timer that started at dial would disagree with the receipt.
 * Even started correctly it is a local clock against a server-side meter, and
 * the caption says so — V03 settles from provider evidence, not from this.
 *
 * **Controls the adapter cannot perform are disabled and explained.** An
 * always-enabled mute button over an adapter without mute is worse than no
 * button: the customer believes they are muted and they are not.
 *
 * **Background audio is disclosed, not discovered.** No adapter has proven that
 * audio survives the app going to background, so when `backgroundCall` is false
 * the panel says so before it matters rather than after a call drops.
 *
 * Not named `ActiveCallScreen`: chunk 04's retirement guard asserts that module
 * no longer exists, and the old name would reintroduce it by string match.
 */

interface CallInProgressProps {
  snapshot: CallSnapshot;
  onHangUp: () => void;
  onToggleMute: () => void;
  onDigit: (digit: string) => void;
  onToggleSpeaker: () => void;
}

function formatElapsed(totalSeconds: number): { minutes: string; seconds: string } {
  const safe = Math.max(0, totalSeconds);
  return {
    minutes: String(Math.floor(safe / 60)).padStart(2, '0'),
    seconds: String(safe % 60).padStart(2, '0'),
  };
}

export function CallInProgress({
  snapshot,
  onHangUp,
  onToggleMute,
  onDigit,
  onToggleSpeaker,
}: CallInProgressProps): React.JSX.Element {
  const { t } = useTranslation('calling');
  const { capabilities } = snapshot;
  // Ticking from answer when answered, and from a frozen point otherwise, so a
  // ringing call shows no running number pretending to be call time.
  const elapsed = useElapsedSeconds(snapshot.answeredAt ?? Date.now());
  const showTimer = snapshot.phase === 'answered' && snapshot.answeredAt !== null;
  const { minutes, seconds } = formatElapsed(showTimer ? elapsed : 0);

  return (
    <View style={styles.panel} testID="call-in-progress">
      <Text style={styles.destination}>{snapshot.destinationE164}</Text>
      <Text style={styles.phase} testID="call-phase">
        {t(`phase.${snapshot.phase}`)}
      </Text>
      {snapshot.identityE164 ? (
        <Text style={styles.meta}>
          {t('preview.identity', { number: snapshot.identityE164 })}
        </Text>
      ) : (
        <Text style={styles.meta}>{t('preview.identityUnknown')}</Text>
      )}

      {showTimer ? (
        <>
          <Text style={styles.timer} testID="call-elapsed">
            {t('elapsed.label', { minutes, seconds })}
          </Text>
          <Text style={styles.caption}>{t('elapsed.estimate')}</Text>
        </>
      ) : null}

      {!capabilities.backgroundCall ? (
        <Text style={styles.disclosure} testID="call-background-disclosure">
          {t('unsupported.background')}
        </Text>
      ) : null}

      <View style={styles.controls}>
        <Pressable
          testID="call-mute"
          accessibilityRole="button"
          accessibilityState={{ disabled: !capabilities.mute, selected: snapshot.muted }}
          disabled={!capabilities.mute}
          onPress={onToggleMute}
          style={[styles.control, !capabilities.mute ? styles.controlDisabled : null]}
        >
          <Text style={styles.controlLabel}>
            {snapshot.muted ? t('action.unmute') : t('action.mute')}
          </Text>
        </Pressable>
        <Pressable
          testID="call-speaker"
          accessibilityRole="button"
          accessibilityState={{
            disabled: !capabilities.audioRoute,
            selected: snapshot.audioRoute === 'speaker',
          }}
          disabled={!capabilities.audioRoute}
          onPress={onToggleSpeaker}
          style={[
            styles.control,
            !capabilities.audioRoute ? styles.controlDisabled : null,
          ]}
        >
          <Text style={styles.controlLabel}>{t('action.speaker')}</Text>
        </Pressable>
      </View>

      {!capabilities.mute ? (
        <Text style={styles.disclosure}>{t('unsupported.mute')}</Text>
      ) : null}
      {!capabilities.dtmf ? (
        <Text style={styles.disclosure} testID="call-dtmf-disclosure">
          {t('unsupported.dtmf')}
        </Text>
      ) : null}

      <Keypad
        onPress={onDigit}
        disabled={!capabilities.dtmf || snapshot.phase !== 'answered'}
        testIDPrefix="call-digit"
      />

      <Pressable
        testID="call-hang-up"
        accessibilityRole="button"
        onPress={onHangUp}
        style={styles.hangUp}
      >
        <Text style={styles.hangUpLabel}>{t('action.hangUp')}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { gap: space.space3, padding: space.space4 },
  destination: { ...typography.heading2, color: color.gray900 },
  phase: { ...typography.body, color: color.gray700 },
  meta: { ...typography.caption, color: color.gray600 },
  timer: { ...typography.display, color: color.gray900 },
  caption: { ...typography.caption, color: color.gray600 },
  disclosure: { ...typography.caption, color: color.warning700 },
  controls: { flexDirection: 'row', gap: space.space3 },
  control: {
    flex: 1,
    minHeight: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.button,
    backgroundColor: color.gray100,
  },
  controlDisabled: { opacity: 0.4 },
  controlLabel: { ...typography.caption, color: color.gray900 },
  hangUp: {
    minHeight: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.button,
    backgroundColor: color.error700,
  },
  hangUpLabel: { ...typography.body, color: color.white, fontWeight: '600' },
});
