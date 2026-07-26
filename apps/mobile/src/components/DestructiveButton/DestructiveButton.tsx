import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';
import { color, minTouchTarget, radius, typography } from '../../theme/tokens';

interface DestructiveButtonProps {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  testID?: string;
}

/**
 * docs/design-system.md §4 — filled error-700, white text, for ordinary
 * irreversible actions (not the named-exception SOS button, which Claude
 * styles directly in SosConfirm/SosSent).
 */
export function DestructiveButton({
  label,
  onPress,
  disabled = false,
  loading = false,
  testID,
}: DestructiveButtonProps): React.JSX.Element {
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
        <ActivityIndicator color={color.white} />
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
    backgroundColor: color.error700,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  buttonPressed: {
    backgroundColor: '#9A2E22',
    transform: [{ scale: 0.98 }],
  },
  buttonDisabled: {
    backgroundColor: color.gray300,
  },
  label: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    fontWeight: '600',
    color: color.white,
  },
  labelDisabled: {
    color: color.gray500,
  },
});
