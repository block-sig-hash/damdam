import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { color, space, typography } from '../../theme/tokens';

interface PlaceholderScreenProps {
  title: string;
  note: string;
}

/**
 * Navigation target for a screen not yet built. Used only for
 * onboarding steps that come after PIN Setup (Family Contact,
 * Departure Date) so PIN Setup is reviewable end-to-end without
 * pretending those later stories are done.
 */
export function PlaceholderScreen({ title, note }: PlaceholderScreenProps): React.JSX.Element {
  return (
    <View style={styles.screen}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.note}>{note}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.space5,
  },
  title: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  note: {
    marginTop: space.space2,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
    textAlign: 'center',
  },
});
