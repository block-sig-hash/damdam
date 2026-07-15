import { Info, X } from 'phosphor-react-native';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

interface EsimActivationBannerProps {
  onActivate: () => void;
  onDismiss: () => void;
}

export function EsimActivationBanner({
  onActivate,
  onDismiss,
}: EsimActivationBannerProps): React.JSX.Element {
  return (
    <View style={styles.banner} testID="esim-activation-banner">
      <Info color={color.info500} size={20} weight="bold" />
      <View style={styles.copy}>
        <Text style={styles.title}>Activate eSIM</Text>
        <Text style={styles.message}>Set up your Saudi Arabia data before you travel.</Text>
        <Pressable
          accessibilityRole="button"
          onPress={onActivate}
          style={styles.action}
          testID="esim-banner-activate"
        >
          <Text style={styles.actionLabel}>Activate now</Text>
        </Pressable>
      </View>
      <Pressable
        accessibilityLabel="Dismiss until next app open"
        accessibilityRole="button"
        onPress={onDismiss}
        style={styles.dismiss}
        testID="esim-banner-dismiss"
      >
        <X color={color.gray700} size={20} weight="bold" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    minHeight: minTouchTarget,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.space3,
    borderLeftWidth: 4,
    borderLeftColor: color.info500,
    borderRadius: radius.button,
    backgroundColor: color.info100,
    paddingVertical: space.space3,
    paddingLeft: space.space4,
  },
  copy: { flex: 1, gap: space.space1 },
  title: {
    ...typography.heading3,
    color: color.gray900,
  },
  message: {
    ...typography.body,
    color: color.gray900,
  },
  action: {
    minHeight: minTouchTarget,
    justifyContent: 'center',
    alignSelf: 'flex-start',
  },
  actionLabel: {
    ...typography.bodyLarge,
    fontWeight: '600',
    color: color.primary500,
  },
  dismiss: {
    width: minTouchTarget,
    height: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
