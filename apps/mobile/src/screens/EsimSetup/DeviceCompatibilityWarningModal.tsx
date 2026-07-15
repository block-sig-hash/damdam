import React from 'react';
import { Modal, StyleSheet, Text, View } from 'react-native';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface DeviceCompatibilityWarningModalProps {
  visible: boolean;
  onContinue: () => void;
  onSupport: () => void;
}

/**
 * Screen 16, docs/frontend-mobile.md — AC-10.3/10.4/10.5. A custom
 * in-app modal per docs/design-system.md §7 ("never a native alert"),
 * not RN's Alert API. `onRequestClose` (Android back gesture / iOS
 * swipe-down) routes to onContinue: the modal has no true neutral
 * exit, so a dismiss is treated the same as tapping Continue for
 * marking the warning "shown" (AC-10.6). The compatibility log
 * itself already fired on detection, before this modal ever
 * rendered — see useEsimSetupIntro.
 */
export function DeviceCompatibilityWarningModal({
  visible,
  onContinue,
  onSupport,
}: DeviceCompatibilityWarningModalProps): React.JSX.Element {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onContinue}
      testID="device-compatibility-warning-modal"
    >
      <View style={styles.backdrop}>
        <View style={styles.card}>
          <Text style={styles.title}>Your device may not support eSIM</Text>
          <Text style={styles.body}>
            Your device does not appear to support eSIM. You can still use your DamDam
            package by scanning the QR code on a compatible device. Tap Continue to
            download your QR code, or tap Support to get help.
          </Text>
          <View style={styles.actions}>
            <PrimaryButton
              testID="esim-warning-continue"
              label="Continue"
              onPress={onContinue}
            />
            <View style={styles.actionSpacing} />
            <SecondaryButton
              testID="esim-warning-support"
              label="Support"
              onPress={onSupport}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(20, 24, 26, 0.5)',
    justifyContent: 'flex-end',
  },
  card: {
    backgroundColor: color.white,
    borderTopLeftRadius: radius.card,
    borderTopRightRadius: radius.card,
    padding: space.space5,
  },
  title: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  body: {
    marginTop: space.space3,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  actions: {
    marginTop: space.space6,
  },
  actionSpacing: {
    height: space.space3,
  },
});
