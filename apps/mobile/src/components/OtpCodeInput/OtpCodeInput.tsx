import React, { useRef } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import {i18n} from '../../i18n';
import { color, radius, typography } from '../../theme/tokens';

interface OtpCodeInputProps {
  length: number;
  value: string;
  onChangeValue: (value: string) => void;
  editable?: boolean;
  autoFocus?: boolean;
  onSubmit?: () => void;
  errored?: boolean;
  testID?: string;
  /** AC-02.2: PIN entry is masked. OTP entry stays plain-digit. */
  masked?: boolean;
  accessibilityLabel?: string;
}

/**
 * Six (or four, for PIN) boxes per docs/design-system.md §4 — "the
 * same box pattern reused for both so it only has to be learned
 * once." A single hidden TextInput drives all boxes so auto-advance
 * falls out of normal text-input behavior instead of hand-rolled
 * per-box focus management.
 */
export function OtpCodeInput({
  length,
  value,
  onChangeValue,
  editable = true,
  autoFocus = true,
  onSubmit,
  errored = false,
  testID = 'otp-code-input',
  masked = false,
  accessibilityLabel = i18n.t('otp.accessibilityLabel', {ns: 'auth'}),
}: OtpCodeInputProps): React.JSX.Element {
  const inputRef = useRef<TextInput>(null);

  return (
    <Pressable
      onPress={() => inputRef.current?.focus()}
      accessibilityRole="none"
      style={styles.row}
    >
      {Array.from({ length }).map((_, index) => {
        const digit = value[index] ?? '';
        const isActive = editable && index === value.length;
        return (
          <View
            key={index}
            style={[
              styles.box,
              isActive && styles.boxActive,
              errored && styles.boxErrored,
            ]}
          >
            <Text style={styles.digit}>{digit ? (masked ? '•' : digit) : ''}</Text>
          </View>
        );
      })}
      <TextInput
        ref={inputRef}
        testID={testID}
        value={value}
        onChangeText={(text) => onChangeValue(text.replace(/\D/g, '').slice(0, length))}
        onSubmitEditing={onSubmit}
        keyboardType="number-pad"
        maxLength={length}
        editable={editable}
        autoFocus={autoFocus}
        secureTextEntry={masked}
        accessibilityLabel={accessibilityLabel}
        style={styles.hiddenInput}
        importantForAutofill="yes"
        textContentType={masked ? 'password' : 'oneTimeCode'}
        caretHidden
      />
    </Pressable>
  );
}

const BOX_SIZE = 48;

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  box: {
    width: BOX_SIZE,
    height: 56,
    borderRadius: radius.button,
    borderWidth: 1.5,
    borderColor: color.gray300,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: color.white,
  },
  boxActive: {
    borderColor: color.primary500,
    borderWidth: 2,
  },
  boxErrored: {
    borderColor: color.error700,
    borderWidth: 2,
  },
  digit: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  hiddenInput: {
    position: 'absolute',
    width: '100%',
    height: '100%',
    opacity: 0,
  },
});
