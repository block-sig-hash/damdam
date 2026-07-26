import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

type BannerTone = 'info' | 'warning' | 'error' | 'neutral';

interface BannerProps {
  tone: BannerTone;
  message: string;
  testID?: string;
  /** docs/design-system.md §4 — "optional trailing action link." */
  actionLabel?: string;
  onAction?: () => void;
}

const TONE_STYLES: Record<BannerTone, { background: string; border: string }> = {
  info: { background: color.info100, border: color.info500 },
  warning: { background: color.warning100, border: color.warning500 },
  error: { background: color.error100, border: color.error700 },
  neutral: { background: color.gray100, border: color.gray100 },
};

/**
 * docs/design-system.md §4 — tint background + gray-900 text +
 * full-saturation left border, never colored text on white (several
 * semantic colors fail body-text contrast on white).
 */
export function Banner({
  tone,
  message,
  testID,
  actionLabel,
  onAction,
}: BannerProps): React.JSX.Element {
  const toneStyle = TONE_STYLES[tone];
  return (
    <View
      testID={testID}
      style={[
        styles.banner,
        { backgroundColor: toneStyle.background, borderLeftColor: toneStyle.border },
      ]}
    >
      <View style={styles.content}>
        <Text style={styles.message}>{message}</Text>
        {actionLabel && onAction ? (
          <Pressable
            accessibilityRole="button"
            onPress={onAction}
            style={styles.actionButton}
            testID={testID ? `${testID}-action` : undefined}
          >
            <Text style={styles.actionLabel}>{actionLabel}</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderLeftWidth: 4,
    borderRadius: radius.button,
    paddingVertical: space.space3,
    paddingHorizontal: space.space4,
  },
  content: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.space3,
  },
  message: {
    flex: 1,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  actionButton: {
    minHeight: minTouchTarget,
    justifyContent: 'center',
  },
  actionLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
});
