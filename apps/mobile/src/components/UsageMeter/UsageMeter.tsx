import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { color, radius, space, typography } from '../../theme/tokens';

/**
 * A remaining-balance meter that is honest about how old its number is.
 *
 * Carrier usage arrives late. A meter that shows "4.2 GB left" with no
 * timestamp is telling someone a number that may be hours behind what they have
 * actually spent, and they will plan around it — which is how a customer runs
 * out of data mid-journey while the app still claims they had plenty.
 *
 * So the reading and its age are one component, and the age is not optional.
 * `observedAt` of `null` means the network has never reported, which is a
 * different statement from "zero used" and renders differently.
 */

interface UsageMeterProps {
  /** "Data" / "Calls", already translated. */
  label: string;
  /** Human-readable remaining and total, e.g. "4.2 GB" / "10 GB". */
  remaining: string;
  total: string;
  /** 0–1. Clamped, because a supplier over-reporting must not overflow the bar. */
  fraction: number;
  /** Rendered age of the reading, or `null` if nothing has ever been reported. */
  updatedLabel: string | null;
  /** True when the reading is old enough that acting on it could mislead. */
  stale?: boolean;
  /** One sentence explaining what "stale" or "never reported" means for them. */
  explanation?: string;
  accessibilityLabel?: string;
  testID?: string;
}

/**
 * Thresholds match the banner thresholds in design-system.md §4, so the meter
 * and any banner about the same balance never disagree about severity.
 */
function fillColor(fraction: number): string {
  if (fraction < 0.05) return color.error700;
  if (fraction < 0.2) return color.warning500;
  return color.success500;
}

export function UsageMeter({
  label,
  remaining,
  total,
  fraction,
  updatedLabel,
  stale = false,
  explanation,
  accessibilityLabel,
  testID,
}: UsageMeterProps): React.JSX.Element {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(fraction) ? fraction : 0));
  const neverReported = updatedLabel === null;

  return (
    <View testID={testID} style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.remaining} testID={testID ? `${testID}-remaining` : undefined}>
          {remaining} / {total}
        </Text>
      </View>

      <View
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel={accessibilityLabel ?? `${label}: ${remaining} / ${total}`}
        accessibilityValue={{ min: 0, max: 100, now: Math.round(clamped * 100) }}
        style={styles.track}
        testID={testID ? `${testID}-track` : undefined}
      >
        <View
          style={[
            styles.fill,
            // A never-reported meter renders an empty track in neutral grey.
            // Painting it full green would be inventing a reading.
            {
              width: `${clamped * 100}%`,
              backgroundColor: neverReported ? color.gray300 : fillColor(clamped),
            },
          ]}
        />
      </View>

      <Text
        style={[styles.updated, stale || neverReported ? styles.updatedStale : null]}
        testID={testID ? `${testID}-updated` : undefined}
      >
        {updatedLabel}
      </Text>
      {explanation ? (
        <Text style={styles.explanation} testID={testID ? `${testID}-explanation` : undefined}>
          {explanation}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: space.space2 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: space.space3,
  },
  label: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.gray700,
  },
  remaining: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  track: {
    height: 8,
    borderRadius: radius.pill,
    backgroundColor: color.gray200,
    overflow: 'hidden',
  },
  fill: { height: '100%', borderRadius: radius.pill },
  updated: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
  },
  // gray700, not a warning colour: a late reading is normal, not a fault, and
  // colouring it as an alert would train people to ignore real alerts.
  updatedStale: { color: color.gray700, fontWeight: '600' },
  explanation: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
  },
});
