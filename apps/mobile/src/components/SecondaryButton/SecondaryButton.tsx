import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';
import { color, minTouchTarget, radius, typography } from '../../theme/tokens';

interface SecondaryButtonProps {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  testID?: string;
}

/** docs/design-system.md §4 — 2px primary-500 border, primary-500 text, same sizing as Primary. */
export function SecondaryButton({
  label,
  onPress,
  disabled = false,
  loading = false,
  testID,
}: SecondaryButtonProps): React.JSX.Element {
  const isDisabled = disabled || loading;
  return (
    <Pressable
      onPress={onPress}
      disabled={isDisabled}
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ disabled: isDisabled, busy: loading }}
      style={({ pressed }) => [
        styles.button,
        isDisabled && styles.buttonDisabled,
        pressed && !isDisabled && styles.buttonPressed,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={color.primary500} />
      ) : (
        <Text style={[styles.label, isDisabled && styles.labelDisabled]}>{label}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: minTouchTarget,
    borderRadius: radius.button,
    borderWidth: 2,
    borderColor: color.primary500,
    backgroundColor: color.white,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  buttonPressed: {
    backgroundColor: color.primary100,
    transform: [{ scale: 0.98 }],
  },
  buttonDisabled: {
    borderColor: color.gray300,
    backgroundColor: color.white,
  },
  label: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
  labelDisabled: {
    color: color.gray500,
  },
});
