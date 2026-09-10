import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { color, radius, space, typography } from '../../theme/tokens';

/**
 * One pill, four independent state families.
 *
 * `data-model.md` §6.44 splits payment, provisioning, installation, activation
 * and network attachment into separate columns on separate tables, because they
 * genuinely disagree — a profile can sit installed on a phone that never
 * attaches, and a line can be suspended with the profile still on the device.
 * A single "status" pill that collapsed them would have to lie about at least
 * one, which is exactly the confusion the schema was reshaped to remove.
 *
 * So the caller says *which question* the pill answers. There is no default:
 * a pill with no family is a pill whose meaning depends on where you found it.
 */

export type StatusTone = 'neutral' | 'progress' | 'positive' | 'caution' | 'negative';

const TONE_STYLE: Record<StatusTone, { background: string; text: string }> = {
  // Tint fill with gray900 text, never a saturated fill with white text. At
  // pill size a light tint is the only pairing that holds AA across every
  // semantic colour at once (design-system.md §1).
  neutral: { background: color.gray100, text: color.gray900 },
  progress: { background: color.info100, text: color.gray900 },
  positive: { background: color.success100, text: color.gray900 },
  caution: { background: color.warning100, text: color.warning700 },
  negative: { background: color.error100, text: color.error700 },
};

interface StatusPillProps {
  /** The state name, already translated. */
  label: string;
  tone: StatusTone;
  /**
   * What question this pill answers — "Payment", "Network". Read out before
   * the value, so a screen reader announces "Network: not connected" rather
   * than an unattached "Not connected" among four other pills.
   */
  family: string;
  testID?: string;
}

export function StatusPill({
  label,
  tone,
  family,
  testID,
}: StatusPillProps): React.JSX.Element {
  const toneStyle = TONE_STYLE[tone];
  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="text"
      accessibilityLabel={`${family}: ${label}`}
      style={[styles.pill, { backgroundColor: toneStyle.background }]}
    >
      <Text style={[styles.label, { color: toneStyle.text }]} numberOfLines={2}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    paddingVertical: space.space1,
    paddingHorizontal: space.space3,
    // Wraps rather than truncating: several French state names are more than
    // twice the length of their English counterparts, and a clipped state is
    // worse than a two-line one.
    maxWidth: '100%',
  },
  label: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
  },
});
