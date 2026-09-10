import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { announce } from '../announce';
import { PrimaryButton } from '../PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

/**
 * Empty, pending, blocked and failed — the four states a screen is in when it
 * has nothing useful to show.
 *
 * They share a shape deliberately. Each one is a heading that says what is
 * true, a sentence that says what it means for the person reading it, and at
 * most one obvious next action. What they must never share is tone: an empty
 * list is not a problem, a failed payment is, and rendering both in the same
 * alarming red teaches people to ignore the colour.
 *
 * `pending` exists as its own variant rather than as a spinner because
 * provisioning is minutes, not milliseconds. A spinner for four minutes reads
 * as a hang; a sentence explaining that the money arrived and the network is
 * working reads as progress.
 */

export type StateVariant = 'empty' | 'pending' | 'blocked' | 'error';

const VARIANT_STYLE: Record<
  StateVariant,
  { background: string; border: string; title: string }
> = {
  empty: { background: color.gray50, border: color.gray200, title: color.gray900 },
  pending: { background: color.info100, border: color.info500, title: color.gray900 },
  blocked: { background: color.warning100, border: color.warning500, title: color.warning700 },
  error: { background: color.error100, border: color.error700, title: color.error700 },
};

interface StateMessageProps {
  variant: StateVariant;
  title: string;
  body: string;
  /** A second sentence that reassures rather than instructs — optional. */
  footnote?: string;
  actionLabel?: string;
  onAction?: () => void;
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
  /** Disables the primary action and shows its in-flight label. */
  busy?: boolean;
  busyLabel?: string;
  testID?: string;
}

export function StateMessage({
  variant,
  title,
  body,
  footnote,
  actionLabel,
  onAction,
  secondaryActionLabel,
  onSecondaryAction,
  busy = false,
  busyLabel,
  testID,
}: StateMessageProps): React.JSX.Element {
  const variantStyle = VARIANT_STYLE[variant];
  return (
    <View
      testID={testID}
      // One node for the whole message, so a screen reader reads the situation
      // as a sentence instead of three disconnected fragments.
      accessible
      accessibilityRole="summary"
      accessibilityLabel={announce(title, body, footnote)}
      style={[
        styles.container,
        { backgroundColor: variantStyle.background, borderColor: variantStyle.border },
      ]}
    >
      <Text
        style={[styles.title, { color: variantStyle.title }]}
        testID={testID ? `${testID}-title` : undefined}
      >
        {title}
      </Text>
      <Text style={styles.body} testID={testID ? `${testID}-body` : undefined}>
        {body}
      </Text>
      {footnote ? (
        <Text style={styles.footnote} testID={testID ? `${testID}-footnote` : undefined}>
          {footnote}
        </Text>
      ) : null}
      {actionLabel && onAction ? (
        <View style={styles.actions}>
          <PrimaryButton
            label={busy && busyLabel ? busyLabel : actionLabel}
            onPress={onAction}
            disabled={busy}
            testID={testID ? `${testID}-action` : undefined}
          />
          {secondaryActionLabel && onSecondaryAction ? (
            <SecondaryButton
              label={secondaryActionLabel}
              onPress={onSecondaryAction}
              testID={testID ? `${testID}-secondary-action` : undefined}
            />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: space.space2,
    padding: space.space5,
    borderWidth: 1,
    borderRadius: radius.card,
  },
  title: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  footnote: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  actions: { gap: space.space3, marginTop: space.space2 },
});
