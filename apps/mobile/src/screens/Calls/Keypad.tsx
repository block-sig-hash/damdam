import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

/**
 * Twelve keys, used for two different jobs (US-47, chunk V04).
 *
 * Before a call it composes a destination. During a call it sends in-band
 * digits so somebody can get through a bank menu. The jobs differ in one way
 * that matters: dialling is local and always works, while DTMF depends on what
 * the adapter can actually do. `disabled` is therefore passed in rather than
 * inferred — a keypad that accepts a digit the adapter will drop leaves the
 * customer believing they navigated a menu they did not.
 *
 * Not named `DialPad`: chunk 04's retirement guard asserts that no
 * `DialPadScreen` module survives, and reusing the retired name here would put
 * the old app-calling surface back in the tree by string match.
 */

const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

interface KeypadProps {
  onPress: (digit: string) => void;
  disabled?: boolean;
  testIDPrefix?: string;
}

export function Keypad({
  onPress,
  disabled = false,
  testIDPrefix = 'keypad',
}: KeypadProps): React.JSX.Element {
  const { t } = useTranslation('calling');
  return (
    <View style={styles.grid} accessibilityLabel={t('action.keypad')}>
      {KEYS.map(key => (
        <Pressable
          key={key}
          testID={`${testIDPrefix}-${key}`}
          accessibilityRole="button"
          accessibilityLabel={key}
          accessibilityState={{ disabled }}
          disabled={disabled}
          onPress={() => onPress(key)}
          style={({ pressed }) => [
            styles.key,
            pressed && !disabled ? styles.keyPressed : null,
            disabled ? styles.keyDisabled : null,
          ]}
        >
          <Text style={styles.keyLabel}>{key}</Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: space.space2,
  },
  key: {
    width: 88,
    minHeight: minTouchTarget,
    paddingVertical: space.space3,
    borderRadius: radius.button,
    backgroundColor: color.gray100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  keyPressed: { backgroundColor: color.gray200 },
  keyDisabled: { opacity: 0.4 },
  keyLabel: { ...typography.numeral, color: color.gray900 },
});
