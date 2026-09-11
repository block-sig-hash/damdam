import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  KeyboardAvoidingView,
  Platform as RNPlatform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { AuthResponse } from '../../api/authClient';
import { Banner } from '../../components/Banner/Banner';
import { LocaleSelector } from '../../components/LocaleSelector/LocaleSelector';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { color, minInputHeight, radius, space, typography } from '../../theme/tokens';
import { useEmailSignIn } from './useEmailSignIn';

interface SignInScreenProps {
  onAuthenticated: (result: AuthResponse, email: string) => void | Promise<void>;
  onRecover: (email: string) => void;
  onUsePhone?: () => void;
  /** Pre-filled when an invitation named the address it was sent to. */
  initialEmail?: string;
  /**
   * Shown above the form when the customer arrived here from a deep link, so
   * they know why they were asked to sign in and that their link is not lost.
   */
  contextMessage?: string;
}

/**
 * Sign in or create an account with an email address (US-37, AC-37.2).
 *
 * One screen for both, because the server answers identically for a known and
 * an unknown address and the app must not undo that. The screen never says
 * "we don't recognize that address"; it says a link has been sent if the
 * address can receive one.
 */
export function SignInScreen({
  onAuthenticated,
  onRecover,
  onUsePhone,
  initialEmail,
  contextMessage,
}: SignInScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const {
    stage,
    email,
    setEmail,
    code,
    setCode,
    busy,
    errorMessage,
    requestLink,
    confirm,
    restart,
  } = useEmailSignIn({ onAuthenticated, initialEmail });

  if (stage === 'confirming') {
    return (
      <View style={styles.screen} testID="sign-in-confirming">
        <StateMessage
          variant="pending"
          title={t('signIn.signingIn')}
          body={t('signIn.checkBody', { email })}
          testID="sign-in-confirming-state"
        />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      behavior={RNPlatform.OS === 'ios' ? 'padding' : undefined}
      style={styles.screen}
    >
      <ScrollView contentContainerStyle={styles.content}>
        <LocaleSelector />

        {contextMessage ? (
          <Banner
            tone="info"
            message={contextMessage}
            testID="sign-in-context"
          />
        ) : null}

        {stage === 'email' ? (
          <>
            <Text style={styles.title}>{t('signIn.title')}</Text>
            <Text style={styles.subtitle}>{t('signIn.subtitle')}</Text>

            <Text style={styles.label}>{t('signIn.emailLabel')}</Text>
            <TextInput
              testID="sign-in-email-input"
              value={email}
              onChangeText={setEmail}
              placeholder={t('signIn.emailPlaceholder')}
              placeholderTextColor={color.gray500}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              autoComplete="email"
              textContentType="emailAddress"
              accessibilityLabel={t('signIn.emailLabel')}
              style={styles.input}
            />

            {errorMessage ? (
              <Banner
                tone="error"
                message={errorMessage}
                testID="sign-in-error"
              />
            ) : null}

            <PrimaryButton
              testID="sign-in-submit"
              label={t('signIn.send')}
              onPress={requestLink}
              loading={busy}
              disabled={busy}
            />
            <SecondaryButton
              testID="sign-in-recovery"
              label={t('signIn.recovery')}
              onPress={() => onRecover(email.trim().toLowerCase())}
            />
            {onUsePhone ? (
              <SecondaryButton
                testID="sign-in-use-phone"
                label={t('signIn.usePhone')}
                onPress={onUsePhone}
              />
            ) : null}
          </>
        ) : (
          <>
            <StateMessage
              variant="pending"
              title={t('signIn.checkTitle')}
              body={t('signIn.checkBody', { email })}
              footnote={t('signIn.checkFootnote')}
              testID="sign-in-sent"
            />

            {errorMessage ? (
              <Banner
                tone="error"
                message={errorMessage}
                testID="sign-in-error"
              />
            ) : null}

            {/*
              The paste field is not a fallback for a broken deep link so much
              as for the ordinary case where mail is read on a different device
              from the one the app is installed on.
            */}
            <Text style={styles.label}>{t('signIn.pasteLabel')}</Text>
            <TextInput
              testID="sign-in-code-input"
              value={code}
              onChangeText={setCode}
              autoCapitalize="none"
              autoCorrect={false}
              accessibilityLabel={t('signIn.pasteLabel')}
              style={styles.input}
            />
            <Text style={styles.hint}>{t('signIn.pasteHint')}</Text>

            <PrimaryButton
              testID="sign-in-code-submit"
              label={t('signIn.pasteAction')}
              onPress={() => confirm()}
              disabled={busy || code.trim().length === 0}
              loading={busy}
            />
            <SecondaryButton
              testID="sign-in-resend"
              label={t('signIn.resend')}
              onPress={requestLink}
              disabled={busy}
            />
            <SecondaryButton
              testID="sign-in-change-email"
              label={t('signIn.useDifferentEmail')}
              onPress={restart}
            />
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.gray50 },
  content: { padding: space.space5, gap: space.space4 },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  subtitle: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  label: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: typography.caption.fontWeight,
    color: color.gray900,
  },
  input: {
    minHeight: minInputHeight,
    borderWidth: 1,
    borderColor: color.gray300,
    borderRadius: radius.button,
    paddingHorizontal: space.space4,
    fontSize: typography.body.fontSize,
    color: color.gray900,
    backgroundColor: color.white,
  },
  hint: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
