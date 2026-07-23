import React, { useEffect } from 'react';
import {useTranslation} from 'react-i18next';
import { Platform as RNPlatform, StyleSheet, Text, View } from 'react-native';
import { AuthResponse } from '../../api/authClient';
import { Banner } from '../../components/Banner/Banner';
import { OtpCodeInput } from '../../components/OtpCodeInput/OtpCodeInput';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import { useReturningPilgrimLogin } from './useReturningPilgrimLogin';

interface ReturningPilgrimScreenProps {
  phoneNumber: string;
  onVerified: (result: AuthResponse) => void;
}

const OTP_CODE_LENGTH = 6;

/**
 * AC-01.7 / AC-07.5 / AC-23.4 — "Welcome back" re-authentication for
 * a phone number that already has an account and no valid local
 * session (a new device, or a session older than 30 days). Reuses
 * the OTP-based recovery pair US-02 built for "forgot my PIN" — see
 * useReturningPilgrimLogin's docstring for why this isn't a PIN-entry
 * form. Reached from Phone Entry's "this number already has an
 * account" branch (docs/frontend-mobile.md §8.2's Flow B).
 */
export function ReturningPilgrimScreen({
  phoneNumber,
  onVerified,
}: ReturningPilgrimScreenProps): React.JSX.Element {
  const {t} = useTranslation('auth');
  const platform = RNPlatform.OS === 'ios' ? 'ios' : 'android';
  const {
    code,
    setCode,
    status,
    errorMessage,
    canResend,
    secondsUntilResend,
    lockoutSecondsRemaining,
    isResending,
    resend,
    submit,
  } = useReturningPilgrimLogin({ phoneNumber, platform, onVerified });

  useEffect(() => {
    if (code.length === OTP_CODE_LENGTH && status === 'awaiting_code') {
      submit();
    }
  }, [code, status, submit]);

  const helperText =
    status === 'sending'
      ? t('otp.sending')
      : status === 'locked'
        ? t('otp.lockedCountdown', {seconds: lockoutSecondsRemaining})
        : t('otp.sentTo', {phone: formatNigerianPhoneForDisplay(phoneNumber)});

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>{t('returning.title')}</Text>
      <Text style={styles.subtitle} testID="returning-pilgrim-helper-text">
        {helperText}
      </Text>

      <View style={styles.codeInput}>
        <OtpCodeInput
          length={OTP_CODE_LENGTH}
          value={code}
          onChangeValue={setCode}
          editable={status !== 'locked' && status !== 'verifying' && status !== 'sending'}
          errored={Boolean(errorMessage) && status !== 'locked'}
          onSubmit={submit}
        />
      </View>

      {errorMessage ? (
        <View style={styles.bannerSpacing}>
          <Banner
            tone={status === 'locked' ? 'warning' : 'error'}
            message={errorMessage}
            testID="returning-pilgrim-error-banner"
          />
        </View>
      ) : null}

      <View style={styles.footer}>
        <PrimaryButton
          testID="returning-pilgrim-submit"
          label={t('otp.verify')}
          onPress={submit}
          disabled={code.length !== OTP_CODE_LENGTH || status === 'locked'}
          loading={status === 'verifying'}
        />

        <Text
          testID="returning-pilgrim-resend-link"
          accessibilityRole="button"
          onPress={canResend ? resend : undefined}
          style={[styles.resendLink, !canResend && styles.resendLinkDisabled]}
        >
          {isResending
            ? t('otp.resending')
            : canResend
              ? t('otp.resend')
              : t('otp.resendCountdown', {seconds: secondsUntilResend})}
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
