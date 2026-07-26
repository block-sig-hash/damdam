import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import type { VerifiedCallerIdentity } from '../../api/cliClient';
import { useCliConsent } from './useCliConsent';

interface CliConsentScreenProps {
  accessToken: string;
  identityId: string;
  phoneNumber: string;
  onConsented: (identity: VerifiedCallerIdentity) => void;
}

/**
 * AC-14.1/prd.md §5.5 -- an explicit, versioned consent capture, distinct
 * from phone-possession proof. Activation requires this step even though
 * the number was just confirmed.
 */
export function CliConsentScreen({
  accessToken,
  identityId,
  phoneNumber,
  onConsented,
}: CliConsentScreenProps): React.JSX.Element {
  const { status, errorMessage, submit } = useCliConsent({
    accessToken,
    identityId,
    onConsented,
  });

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Use this number as your caller ID</Text>
      <Text style={styles.subtitle}>
        {formatNigerianPhoneForDisplay(phoneNumber.replace('+234', '0'))} is verified. Confirm
        you want family and other recipients to see this number when you call
        them from DamDam.
      </Text>

      <View style={styles.card}>
        <Text style={styles.cardText}>
          You can change your mind at any time. Revoking, or reporting the SIM
          as lost, immediately stops new calls from showing this number -- any
          call already in progress is not affected.
        </Text>
      </View>

      {errorMessage ? (
        <Banner tone="error" message={errorMessage} testID="cli-consent-error" />
      ) : null}

      <PrimaryButton
        testID="cli-consent-submit"
        label="Agree and activate"
        onPress={submit}
        loading={status === 'submitting'}
      />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flexGrow: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
    gap: space.space4,
  },
  title: { ...typography.heading1, color: color.gray900 },
  subtitle: { ...typography.bodyLarge, color: color.gray700 },
  card: {
    backgroundColor: color.white,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    padding: space.space4,
  },
  cardText: { ...typography.body, color: color.gray700 },
});
