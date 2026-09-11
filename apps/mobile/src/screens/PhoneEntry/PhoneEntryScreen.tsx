import React from 'react';
import {useTranslation} from 'react-i18next';
import { KeyboardAvoidingView, Platform as RNPlatform, StyleSheet, Text, TextInput, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import {LocaleSelector} from '../../components/LocaleSelector/LocaleSelector';
import { color, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import { usePhoneEntry } from './usePhoneEntry';

interface PhoneEntryScreenProps {
  onOtpSent: (phoneNumber: string) => void;
  onAccountExists: (phoneNumber: string) => void;
  onCancel?: () => void;
}

/**
 * US-01 / prd.md §4.1 — AC-01.1, AC-01.2, AC-01.3, AC-01.7.
 * Screen 2 of the onboarding flow (docs/frontend-mobile.md §8.1).
 */
export function PhoneEntryScreen({
  onOtpSent,
  onAccountExists,
  onCancel,
}: PhoneEntryScreenProps): React.JSX.Element {
  const {t} = useTranslation('auth');
  const { phoneNumber, setPhoneNumber, isValid, status, errorMessage, submit } = usePhoneEntry({
    onOtpSent,
    onAccountExists,
  });
  const showFormatHint = phoneNumber.length > 0 && !isValid;

  return (
    <KeyboardAvoidingView
      behavior={RNPlatform.OS === 'ios' ? 'padding' : undefined}
      style={styles.screen}
    >
      <LocaleSelector />
      <Text style={styles.title}>{t('phone.title')}</Text>
      <Text style={styles.subtitle}>{t('phone.subtitle')}</Text>

      <Text style={styles.label}>{t('phone.label')}</Text>
      <TextInput
        testID="phone-entry-input"
        value={formatNigerianPhoneForDisplay(phoneNumber)}
        onChangeText={setPhoneNumber}
        placeholder="080 1234 5678"
        placeholderTextColor={color.gray500}
        keyboardType="number-pad"
        maxLength={13}
        accessibilityLabel={t('phone.label')}
        style={[styles.input, showFormatHint && styles.inputError]}
      />
      {showFormatHint ? (
        <Text style={styles.hint}>
          {t('phone.hint')}
        </Text>
      ) : null}

      {errorMessage ? (
        <View style={styles.bannerSpacing}>
          <Banner tone="error" message={errorMessage} testID="phone-entry-error" />
        </View>
      ) : null}

      <View style={styles.footer}>
        <PrimaryButton
          testID="phone-entry-submit"
          label={t('phone.sendCode')}
          onPress={submit}
          disabled={!isValid}
          loading={status === 'submitting'}
        />
        {onCancel ? (
          <SecondaryButton
            testID="phone-entry-cancel"
            label={t('phone.useEmail')}
            onPress={onCancel}
          />
        ) : null}
      </View>
    </KeyboardAvoidingView>
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
  label: {
    marginTop: space.space8,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.gray700,
  },
  input: {
    marginTop: space.space2,
    minHeight: 52,
    borderWidth: 1.5,
    borderColor: color.gray300,
    borderRadius: 12,
    paddingHorizontal: space.space4,
    fontSize: typography.bodyLarge.fontSize,
    color: color.gray900,
    backgroundColor: color.white,
  },
  inputError: {
    borderColor: color.error700,
    borderWidth: 2,
  },
  hint: {
    marginTop: space.space2,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.error700,
  },
  bannerSpacing: {
    marginTop: space.space4,
  },
  footer: {
    marginTop: space.space8,
  },
});
