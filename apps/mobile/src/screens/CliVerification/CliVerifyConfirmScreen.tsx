import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { OtpCodeInput } from '../../components/OtpCodeInput/OtpCodeInput';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, space, typography } from '../../theme/tokens';
import { formatNigerianPhoneForDisplay } from '../../utils/phoneNumber';
import type { VerifiedCallerIdentity } from '../../api/cliClient';
import { CLI_CONFIRM_CODE_LENGTH, useCliVerifyConfirm } from './useCliVerifyConfirm';

interface CliVerifyConfirmScreenProps {
  accessToken: string;
  identityId: string;
  phoneNumber: string;
  onConfirmed: (identity: VerifiedCallerIdentity) => void;
  onUseDifferentNumber: () => void;
}

export function CliVerifyConfirmScreen({
  accessToken,
  identityId,
  phoneNumber,
  onConfirmed,
  onUseDifferentNumber,
}: CliVerifyConfirmScreenProps): React.JSX.Element {
  const { code, setCode, status, errorMessage, locked, submit } = useCliVerifyConfirm({
    accessToken,
    identityId,
    onConfirmed,
  });

  return (
    <View style={styles.screen}>
      <Text style={styles.title}>Enter your code</Text>
      <Text style={styles.subtitle} testID="cli-confirm-helper-text">
        Enter the code sent to {formatNigerianPhoneForDisplay(phoneNumber.replace('+234', '0'))}.
      </Text>

      <View style={styles.codeInput}>
        <OtpCodeInput
          length={CLI_CONFIRM_CODE_LENGTH}
          value={code}
          onChangeValue={setCode}
          editable={status !== 'verifying' && !locked}
          errored={Boolean(errorMessage)}
          onSubmit={submit}
          accessibilityLabel="Verification code"
          testID="cli-confirm-code-input"
        />
      </View>

      {errorMessage ? (
        <Banner
          tone={locked ? 'warning' : 'error'}
          message={errorMessage}
          testID="cli-confirm-error"
        />
      ) : null}

      <PrimaryButton
        testID="cli-confirm-submit"
        label="Verify"
        onPress={submit}
        disabled={code.length !== CLI_CONFIRM_CODE_LENGTH || locked}
        loading={status === 'verifying'}
      />
      <Text
        testID="cli-confirm-use-different-number"
        accessibilityRole="button"
        onPress={onUseDifferentNumber}
        style={styles.link}
      >
        Use a different number
      </Text>
    </View>
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
  codeInput: { marginTop: space.space4 },
  link: {
    ...typography.caption,
    fontWeight: '600',
    textAlign: 'center',
    color: color.primary500,
  },
});
