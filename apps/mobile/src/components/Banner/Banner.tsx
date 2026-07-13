import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { color, radius, space, typography } from '../../theme/tokens';

type BannerTone = 'info' | 'warning' | 'error' | 'neutral';

interface BannerProps {
  tone: BannerTone;
  message: string;
  testID?: string;
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
export function Banner({ tone, message, testID }: BannerProps): React.JSX.Element {
  const toneStyle = TONE_STYLES[tone];
  return (
    <View
      testID={testID}
      style={[
        styles.banner,
        { backgroundColor: toneStyle.background, borderLeftColor: toneStyle.border },
      ]}
    >
      <Text style={styles.message}>{message}</Text>
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
  message: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
});
