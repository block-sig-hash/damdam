import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, Vibration, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { color, space, typography } from '../../theme/tokens';

// docs/design-system.md §6 — 3000ms, linear (never eased): a safety
// countdown must let the user predict exactly how much time remains.
const HOLD_DURATION_MS = 3000;
const TICK_MS = 50;
const RING_SIZE = 220;
const RING_STROKE = 12;
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

export interface SosConfirmScreenProps {
  onConfirmed: () => void | Promise<void>;
}

export function SosConfirmScreen({ onConfirmed }: SosConfirmScreenProps): React.JSX.Element {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [holding, setHolding] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastSecondRef = useRef(3);

  const clearHold = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => clearHold, [clearHold]);

  const handlePressIn = useCallback(() => {
    clearHold();
    lastSecondRef.current = 3;
    setElapsedMs(0);
    setHolding(true);
    const startedAt = Date.now();
    intervalRef.current = setInterval(() => {
      const next = Date.now() - startedAt;
      if (next >= HOLD_DURATION_MS) {
        clearHold();
        setElapsedMs(HOLD_DURATION_MS);
        setHolding(false);
        // Stronger, longer completion haptic — distinct from the per-second tick.
        Vibration.vibrate(120);
        Promise.resolve(onConfirmed()).catch(() => undefined);
        return;
      }
      setElapsedMs(next);
      const secondsLeft = 3 - Math.floor(next / 1000);
      if (secondsLeft !== lastSecondRef.current) {
        lastSecondRef.current = secondsLeft;
        Vibration.vibrate(20);
      }
    }, TICK_MS);
  }, [clearHold, onConfirmed]);

  const handlePressOut = useCallback(() => {
    // Release before completion cancels silently: no action, no log entry —
    // this avoids noise from ordinary mis-taps (docs/design-system.md §6).
    clearHold();
    setHolding(false);
    setElapsedMs(0);
    lastSecondRef.current = 3;
  }, [clearHold]);

  const progress = Math.min(elapsedMs / HOLD_DURATION_MS, 1);
  const secondsLeft = Math.max(1, 3 - Math.floor(elapsedMs / 1000));

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Emergency SOS</Text>
      <Text style={styles.instructions}>
        Press and hold the button below for 3 seconds to alert your operator and family.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="SOS / Emergency"
        accessibilityHint="Press and hold for 3 seconds to send an emergency alert"
        onPressIn={handlePressIn}
        onPressOut={handlePressOut}
        style={styles.buttonWrap}
      >
        <Svg width={RING_SIZE} height={RING_SIZE} style={StyleSheet.absoluteFill}>
          <Circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RING_RADIUS}
            stroke={color.gray200}
            strokeWidth={RING_STROKE}
            fill="none"
          />
          <Circle
            cx={RING_SIZE / 2}
            cy={RING_SIZE / 2}
            r={RING_RADIUS}
            stroke={color.error700}
            strokeWidth={RING_STROKE}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={`${RING_CIRCUMFERENCE}, ${RING_CIRCUMFERENCE}`}
            strokeDashoffset={RING_CIRCUMFERENCE * (1 - progress)}
            rotation={-90}
            origin={`${RING_SIZE / 2}, ${RING_SIZE / 2}`}
          />
        </Svg>
        <View style={styles.buttonCore}>
          <Text style={styles.buttonLabel}>SOS</Text>
          {holding ? (
            <Text style={styles.countdown} accessibilityLiveRegion="polite">
              {secondsLeft}
            </Text>
          ) : null}
        </View>
      </Pressable>
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
    justifyContent: 'center',
    gap: space.space6,
  },
  title: { ...typography.heading1, color: color.gray900, textAlign: 'center' },
  instructions: {
    ...typography.bodyLarge,
    color: color.gray700,
    textAlign: 'center',
    paddingHorizontal: space.space4,
  },
  buttonWrap: {
    width: RING_SIZE,
    height: RING_SIZE,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonCore: {
    width: RING_SIZE - RING_STROKE * 3,
    height: RING_SIZE - RING_STROKE * 3,
    borderRadius: (RING_SIZE - RING_STROKE * 3) / 2,
    backgroundColor: color.error700,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.space2,
  },
  buttonLabel: { ...typography.heading1, color: color.white },
  countdown: { ...typography.display, color: color.white },
});
