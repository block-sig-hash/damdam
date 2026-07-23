import React, { useEffect } from 'react';
import {useTranslation} from 'react-i18next';
import { StyleSheet, Text, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { OtpCodeInput } from '../../components/OtpCodeInput/OtpCodeInput';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { PIN_LENGTH, usePinSetup } from './usePinSetup';

interface PinSetupScreenProps {
  accessToken: string;
  onPinSet: () => void;
}

/**
 * US-02 / prd.md §4.1 — AC-02.1 through AC-02.4. Screen 4 of the
 * onboarding flow (docs/frontend-mobile.md §8.1), directly following
 * OTP Verification.
 */
export function PinSetupScreen({
  accessToken,
  onPinSet,
}: PinSetupScreenProps): React.JSX.Element {
  const {t} = useTranslation(['auth', 'common']);
  const { stage, value, setValue, errorMessage, submit } = usePinSetup({
    accessToken,
    onPinSet,
  });

  useEffect(() => {
    if (value.length === PIN_LENGTH && stage !== 'submitting') {
      submit();
    }
  }, [value, stage, submit]);

  const entering = stage === 'enter';
  const title = entering ? t('pinSetup.createTitle') : t('pinSetup.confirmTitle');
  const subtitle = entering ? t('pinSetup.createSubtitle') : t('pinSetup.confirmSubtitle');

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.subtitle} testID="pin-setup-helper-text">
        {subtitle}
      </Text>

      <View style={styles.codeInput}>
        <OtpCodeInput
          length={PIN_LENGTH}
          value={value}
          onChangeValue={setValue}
          editable={stage !== 'submitting'}
          errored={Boolean(errorMessage)}
          onSubmit={submit}
          masked
          testID="pin-setup-input"
          accessibilityLabel={entering ? t('pinSetup.createAccessibility') : t('pinSetup.confirmAccessibility')}
        />
      </View>

      {errorMessage ? (
        <View style={styles.bannerSpacing}>
          <Banner tone="error" message={errorMessage} testID="pin-setup-error-banner" />
        </View>
      ) : null}

      <View style={styles.footer}>
        <PrimaryButton
          testID="pin-setup-submit"
          label={entering ? t('actions.continue', {ns: 'common'}) : t('pinSetup.confirmAction')}
          onPress={submit}
          disabled={value.length !== PIN_LENGTH}
          loading={stage === 'submitting'}
        />
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
});
