import React, { useEffect } from 'react';
import {useTranslation} from 'react-i18next';
import {
  KeyboardAvoidingView,
  Platform as RNPlatform,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { ACTIVATION_CODE_LENGTH, useActivationCodeEntry } from './useActivationCodeEntry';

interface ActivationCodeEntryScreenProps {
  initialCode?: string;
  onContinue: (activationCode: string) => void;
}

/**
 * US-07 / prd.md §4.2 — AC-07.2. Screen 13 of the onboarding flow
 * (docs/frontend-mobile.md §8.1), the entry point for Flow B (§8.2).
 */
export function ActivationCodeEntryScreen({
  initialCode,
  onContinue,
}: ActivationCodeEntryScreenProps): React.JSX.Element {
  const {t} = useTranslation(['auth', 'common']);
  const { code, setCode, status, preview, errorMessage, canContinue, checkCode } =
    useActivationCodeEntry({ initialCode });

  useEffect(() => {
    if (code.length === ACTIVATION_CODE_LENGTH && status === 'idle') {
      checkCode();
    }
  }, [code, status, checkCode]);

  return (
    <KeyboardAvoidingView
      behavior={RNPlatform.OS === 'ios' ? 'padding' : undefined}
      style={styles.screen}
    >
      <Text style={styles.title}>{t('activation.entryTitle')}</Text>
      <Text style={styles.subtitle}>{t('activation.entrySubtitle')}</Text>

      <Text style={styles.label}>{t('activation.codeLabel')}</Text>
      <TextInput
        testID="activation-code-input"
        value={code}
        onChangeText={setCode}
        placeholder="ABCD1234"
        placeholderTextColor={color.gray500}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={ACTIVATION_CODE_LENGTH}
        accessibilityLabel={t('activation.codeLabel')}
        style={[styles.input, status === 'invalid' && styles.inputError]}
      />

      {status === 'valid' && preview ? (
        <View style={styles.previewCard} testID="activation-preview-card">
          <Text style={styles.previewLabel}>{t('activation.issuedBy')}</Text>
          <Text style={styles.previewValue}>{preview.organization_name}</Text>
          <Text style={styles.previewLabel}>{t('activation.package')}</Text>
          <Text style={styles.previewValue}>{preview.pricing_tier_name}</Text>
        </View>
      ) : null}

      {errorMessage ? (
        <View style={styles.bannerSpacing}>
          <Banner tone="error" message={errorMessage} testID="activation-code-error" />
        </View>
      ) : null}

      <View style={styles.footer}>
        <PrimaryButton
          testID="activation-code-continue"
          label={t('actions.continue', {ns: 'common'})}
          onPress={() => onContinue(code)}
          disabled={!canContinue}
          loading={status === 'checking'}
        />
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
    letterSpacing: 2,
  },
  inputError: {
    borderColor: color.error700,
    borderWidth: 2,
  },
  previewCard: {
    marginTop: space.space5,
    padding: space.space4,
    borderRadius: radius.card,
    backgroundColor: color.success100,
  },
  previewLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  previewValue: {
    marginBottom: space.space2,
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    fontWeight: '600',
    color: color.success700,
  },
  bannerSpacing: {
    marginTop: space.space4,
  },
  footer: {
    marginTop: space.space8,
  },
});
