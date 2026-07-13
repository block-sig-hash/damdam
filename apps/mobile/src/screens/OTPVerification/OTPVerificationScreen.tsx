import React, { useEffect } from 'react';
import { Platform as RNPlatform, StyleSheet, Text, View } from 'react-native';
import { AuthResponse } from '../../api/authClient';
import { Banner } from '../../components/Banner/Banner';
import { OtpCodeInput } from '../../components/OtpCodeInput/OtpCodeInput';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import { useOtpVerification } from './useOtpVerification';

interface OTPVerificationScreenProps {
  phoneNumber: string;
  onVerified: (result: AuthResponse) => void;
}

const OTP_CODE_LENGTH = 6;

/**
 * US-01 / prd.md §4.1 — AC-01.4, AC-01.5, AC-01.6, AC-01.9.
 * Screen 3 of the onboarding flow (docs/frontend-mobile.md §8.1).
 */
export function OTPVerificationScreen({
  phoneNumber,
  onVerified,
}: OTPVerificationScreenProps): React.JSX.Element {
  const platform = RNPlatform.OS === 'ios' ? 'ios' : 'android';
  const {
    code,
    setCode,
    status,
    errorMessage,
    showSendingReassurance,
    canResend,
    secondsUntilResend,
    lockoutSecondsRemaining,
    isResending,
    resend,
    submit,
  } = useOtpVerification({ phoneNumber, platform, onVerified });

  useEffect(() => {
    if (code.length === OTP_CODE_LENGTH && status === 'awaiting_code') {
      submit();
    }
  }, [code, status, submit]);

  const helperText =
    status === 'locked'
      ? `Too many attempts. Try again in ${lockoutSecondsRemaining}s.`
      : showSendingReassurance
        ? 'Sending your code...'
        : `Enter the 6-digit code sent to ${formatNigerianPhoneForDisplay(phoneNumber)}.`;

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Enter your code</Text>
      <Text style={styles.subtitle} testID="otp-helper-text">
        {helperText}
      </Text>

      <View style={styles.codeInput}>
        <OtpCodeInput
          length={OTP_CODE_LENGTH}
          value={code}
          onChangeValue={setCode}
          editable={status !== 'locked' && status !== 'verifying'}
          errored={Boolean(errorMessage) && status !== 'locked'}
          onSubmit={submit}
        />
      </View>

      {errorMessage ? (
        <View style={styles.bannerSpacing}>
          <Banner
            tone={status === 'locked' ? 'warning' : 'error'}
            message={errorMessage}
            testID="otp-error-banner"
          />
        </View>
      ) : null}

      <View style={styles.footer}>
        <PrimaryButton
          testID="otp-verify-submit"
          label="Verify"
          onPress={submit}
          disabled={code.length !== OTP_CODE_LENGTH || status === 'locked'}
          loading={status === 'verifying'}
        />

        <Text
          testID="otp-resend-link"
          accessibilityRole="button"
          onPress={canResend ? resend : undefined}
          style={[styles.resendLink, !canResend && styles.resendLinkDisabled]}
        >
          {isResending
            ? 'Resending...'
            : canResend
              ? 'Resend code'
              : `Resend code in ${secondsUntilResend}s`}
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
  resendLink: {
    marginTop: space.space4,
    textAlign: 'center',
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
  resendLinkDisabled: {
    color: color.gray500,
  },
});
