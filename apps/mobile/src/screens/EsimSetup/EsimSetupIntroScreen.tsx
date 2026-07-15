import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { DeviceCompatibilityWarningModal } from './DeviceCompatibilityWarningModal';
import { useEsimSetupIntro } from './useEsimSetupIntro';

interface EsimSetupIntroScreenProps {
  accessToken: string;
  packageId: string;
  /**
   * Hands off to whatever the QR/download screen resolves to —
   * US-11's scope, not built here. Called once the compatibility
   * check (and, if unsupported, the warning modal) has resolved.
   */
  onProceed: (packageId: string) => void;
}

/**
 * Screen 15, docs/frontend-mobile.md §8.1 — AC-10.1/10.2. "First
 * checkpoint after purchase," runs the platform-specific device
 * check silently on load.
 */
export function EsimSetupIntroScreen({
  accessToken,
  packageId,
  onProceed,
}: EsimSetupIntroScreenProps): React.JSX.Element {
  const { stage, handleWarningContinue, handleWarningSupport } = useEsimSetupIntro({
    accessToken,
    packageId,
  });

  if (stage === 'checking') {
    return (
      <View style={[styles.screen, styles.centered]} testID="esim-setup-checking">
        <ActivityIndicator color={color.primary500} size="large" />
        <Text style={styles.checkingText}>Checking your device...</Text>
      </View>
    );
  }

  return (
    <View style={styles.screen} testID="esim-setup-intro">
      <Text style={styles.title}>Set up your eSIM</Text>
      {stage === 'compatible' ? (
        <>
          <Text style={styles.body}>
            Your device supports eSIM. Download it directly, or scan a QR code instead.
          </Text>
          <View style={styles.footer}>
            <PrimaryButton
              testID="esim-setup-download"
              label="Download to device"
              onPress={() => onProceed(packageId)}
            />
          </View>
        </>
      ) : (
        <>
          <Text style={styles.body}>
            Use the QR code to activate your DamDam package on a compatible device.
          </Text>
          <View style={styles.footer}>
            <PrimaryButton
              testID="esim-setup-view-qr"
              label="View QR code"
              onPress={() => onProceed(packageId)}
            />
          </View>
        </>
      )}
      <DeviceCompatibilityWarningModal
        visible={stage === 'warning'}
        onContinue={handleWarningContinue}
        onSupport={handleWarningSupport}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
  },
  centered: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkingText: {
    marginTop: space.space3,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  body: {
    marginTop: space.space3,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  footer: {
    marginTop: space.space6,
  },
});
