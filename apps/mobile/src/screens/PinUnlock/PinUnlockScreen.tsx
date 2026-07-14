import React, { useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { AuthResponse } from '../../api/authClient';
import { Banner } from '../../components/Banner/Banner';
import { OtpCodeInput } from '../../components/OtpCodeInput/OtpCodeInput';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { ReturningPilgrimScreen } from '../ReturningPilgrim/ReturningPilgrimScreen';
import { PIN_LENGTH, usePinUnlock } from './usePinUnlock';

interface PinUnlockScreenProps {
  phoneNumber: string;
  onUnlocked: (recovered?: AuthResponse) => void;
}

/**
 * US-02/US-23 — AC-02.3/AC-23.3, AC-02.4/AC-23.5. Screen 31 of
 * docs/frontend-mobile.md §8.1, the app-open PIN gate. Reuses PIN
 * Setup's masked OtpCodeInput and Returning Pilgrim's OTP-recovery
 * flow rather than reinventing either.
 */
export function PinUnlockScreen({
  phoneNumber,
  onUnlocked,
}: PinUnlockScreenProps): React.JSX.Element {
  const {
    stage,
    value,
    setValue,
    errorMessage,
    lockoutSecondsRemaining,
    submit,
    isRecovering,
    startRecovery,
    cancelRecovery,
    handleRecovered,
  } = usePinUnlock({ onUnlocked });

  useEffect(() => {
    if (value.length === PIN_LENGTH && stage === 'entry') {
      submit();
    }
  }, [value, stage, submit]);

  if (isRecovering) {
    return (
      <View style={styles.screen}>
        <ReturningPilgrimScreen phoneNumber={phoneNumber} onVerified={handleRecovered} />
        <Text
          testID="pin-unlock-cancel-recovery"
          accessibilityRole="button"
          onPress={cancelRecovery}
          style={styles.footerLink}
        >
          Back to PIN entry
        </Text>
      </View>
    );
  }

  if (stage === 'checking') {
    return (
      <View style={styles.screen}>
        <Text style={styles.title}>Unlock DamDam</Text>
      </View>
    );
  }

  if (stage === 'no-local-pin') {
    return (
      <View style={styles.screen}>
        <Text style={styles.title}>Verify it&apos;s you</Text>
        <Text style={styles.subtitle} testID="pin-unlock-helper-text">
          This device doesn&apos;t have a PIN set up yet. Verify with a one-time code instead.
        </Text>
        <View style={styles.footer}>
          <PrimaryButton
            testID="pin-unlock-start-recovery"
            label="Verify via OTP"
            onPress={startRecovery}
          />
        </View>
      </View>
    );
  }

  const helperText =
    stage === 'locked'
      ? `Too many attempts. Try again in ${lockoutSecondsRemaining}s, or verify via OTP.`
      : 'Enter your 4-digit PIN to continue.';

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Unlock DamDam</Text>
      <Text style={styles.subtitle} testID="pin-unlock-helper-text">
        {helperText}
      </Text>

      <View style={styles.codeInput}>
        <OtpCodeInput
          length={PIN_LENGTH}
          value={value}
          onChangeValue={setValue}
          editable={stage === 'entry'}
          errored={Boolean(errorMessage) && stage !== 'locked'}
          onSubmit={submit}
          masked
          testID="pin-unlock-input"
          accessibilityLabel="Enter PIN"
        />
      </View>

      {errorMessage ? (
        <View style={styles.bannerSpacing}>
          <Banner
            tone={stage === 'locked' ? 'warning' : 'error'}
            message={errorMessage}
            testID="pin-unlock-error-banner"
          />
        </View>
      ) : null}

      <View style={styles.footer}>
        <PrimaryButton
          testID="pin-unlock-submit"
          label="Unlock"
          onPress={submit}
          disabled={value.length !== PIN_LENGTH || stage === 'locked'}
        />
        <Text
          testID="pin-unlock-recovery-link"
          accessibilityRole="button"
          onPress={startRecovery}
          style={styles.footerLink}
        >
          Forgot your PIN? Verify via OTP
        </Text>
      </View>
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
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  subtitle: {
    marginTop: space.space2,
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray700,
  },
  codeInput: {
    marginTop: space.space8,
  },
  bannerSpacing: {
    marginTop: space.space4,
  },
  footer: {
    marginTop: space.space8,
  },
  footerLink: {
    marginTop: space.space4,
    textAlign: 'center',
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
});
