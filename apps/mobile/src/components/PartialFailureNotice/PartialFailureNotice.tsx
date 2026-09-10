import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { announce } from '../announce';
import { PrimaryButton } from '../PrimaryButton/PrimaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

/**
 * "38 of 40 lines are ready. Two failed."
 *
 * A bulk order is not one outcome. Reporting it as a single success hides two
 * people who have no service, and reporting it as a single failure implies
 * thirty-eight orders that worked need doing again — and someone acting on
 * that impression is how a batch gets bought twice.
 *
 * The count of failures leads, because that is the number the reader has to act
 * on. The count that succeeded follows immediately, because it is the number
 * that stops them panicking. And the retry says out loud that it does not
 * charge again, because with money already taken that is the question anybody
 * has before pressing it.
 */

interface PartialFailureNoticeProps {
  total: number;
  succeeded: number;
  /** Localized "{failed} of {total} lines could not be set up". */
  title: string;
  /** Localized, already pluralized for `succeeded`. */
  body: string;
  retryLabel: string;
  /** "Retrying does not charge you again." */
  noChargeNote: string;
  onRetry: () => void;
  retrying?: boolean;
  retryingLabel?: string;
  testID?: string;
}

export function PartialFailureNotice({
  total,
  succeeded,
  title,
  body,
  retryLabel,
  noChargeNote,
  onRetry,
  retrying = false,
  retryingLabel,
  testID,
}: PartialFailureNoticeProps): React.JSX.Element {
  const failed = Math.max(0, total - succeeded);
  return (
    <View
      testID={testID}
      accessible
      accessibilityRole="summary"
      accessibilityLabel={announce(title, body, noChargeNote)}
      style={styles.container}
    >
      <Text style={styles.title} testID={testID ? `${testID}-title` : undefined}>
        {title}
      </Text>
      <Text style={styles.body} testID={testID ? `${testID}-body` : undefined}>
        {body}
      </Text>
      <Text style={styles.note} testID={testID ? `${testID}-no-charge` : undefined}>
        {noChargeNote}
      </Text>
      {failed > 0 ? (
        <PrimaryButton
          label={retrying && retryingLabel ? retryingLabel : retryLabel}
          onPress={onRetry}
          loading={retrying}
          testID={testID ? `${testID}-retry` : undefined}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: space.space2,
    padding: space.space5,
    borderWidth: 1,
    borderColor: color.warning500,
    borderRadius: radius.card,
    // Caution, not error: most of the batch worked, and the part that did not
    // is recoverable without paying again.
    backgroundColor: color.warning100,
  },
  title: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.warning700,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  note: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
    marginBottom: space.space1,
  },
});
