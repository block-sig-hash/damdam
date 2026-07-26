import React from 'react';
import { KeyboardAvoidingView, Platform as RNPlatform, StyleSheet, Text, TextInput } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import type { VerifiedCallerIdentity } from '../../api/cliClient';
import { useCliVerifyEntry } from './useCliVerifyEntry';

interface CliVerifyEntryScreenProps {
  accessToken: string;
  onStarted: (identity: VerifiedCallerIdentity) => void;
  onCancel: () => void;
}

/**
 * AC-14.1/AC-14.10 -- a dedicated CLI verification flow, decoupled from
 * account login. A pilgrim may verify possession of any Nigerian mobile
 * number here, independent of which number they signed in with.
 */
export function CliVerifyEntryScreen({
  accessToken,
  onStarted,
  onCancel,
}: CliVerifyEntryScreenProps): React.JSX.Element {
  const { phoneNumber, setPhoneNumber, isValid, status, errorMessage, submit } =
    useCliVerifyEntry({ accessToken, onStarted });
  const showFormatHint = phoneNumber.length > 0 && !isValid;

  return (
    <KeyboardAvoidingView
      behavior={RNPlatform.OS === 'ios' ? 'padding' : undefined}
      style={styles.screen}
    >
      <Text style={styles.title}>Verify your caller ID</Text>
      <Text style={styles.subtitle}>
        Family see this exact number when you call them. It doesn't have to be
        the number you signed in with.
      </Text>

      <Text style={styles.label}>Nigerian mobile number</Text>
      <TextInput
        testID="cli-verify-entry-input"
        value={formatNigerianPhoneForDisplay(phoneNumber)}
        onChangeText={setPhoneNumber}
        placeholder="080 1234 5678"
        placeholderTextColor={color.gray500}
        keyboardType="number-pad"
        maxLength={13}
        accessibilityLabel="Nigerian mobile number"
        style={[styles.input, showFormatHint && styles.inputError]}
      />
      {showFormatHint ? (
        <Text style={styles.hint}>
          Enter an 11-digit Nigerian mobile number, e.g. 080 1234 5678.
        </Text>
      ) : null}

      {errorMessage ? (
        <Banner tone="error" message={errorMessage} testID="cli-verify-entry-error" />
      ) : null}

      <PrimaryButton
        testID="cli-verify-entry-submit"
        label="Send code"
        onPress={submit}
        disabled={!isValid}
        loading={status === 'submitting'}
      />
      <Text
        testID="cli-verify-entry-cancel"
        accessibilityRole="button"
        onPress={onCancel}
        style={styles.cancelLink}
      >
        Not now
      </Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
    gap: space.space4,
  },
  title: { ...typography.heading1, color: color.gray900 },
  subtitle: { ...typography.bodyLarge, color: color.gray700 },
  label: {
    ...typography.caption,
    fontWeight: '600',
    color: color.gray700,
    marginTop: space.space4,
  },
  input: {
    minHeight: 52,
    borderWidth: 1.5,
    borderColor: color.gray300,
    borderRadius: 12,
    paddingHorizontal: space.space4,
    fontSize: typography.bodyLarge.fontSize,
    color: color.gray900,
    backgroundColor: color.white,
  },
  inputError: { borderColor: color.error700, borderWidth: 2 },
  hint: { ...typography.caption, color: color.error700 },
  cancelLink: {
    ...typography.caption,
    fontWeight: '600',
    textAlign: 'center',
    color: color.primary500,
  },
});
