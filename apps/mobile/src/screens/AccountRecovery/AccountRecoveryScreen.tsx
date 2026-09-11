import React, { useCallback, useState } from 'react';
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
import { ApiError } from '../../api/http';
import {
  confirmEmailRecovery,
  requestEmailRecovery,
  type RecoverySession,
} from '../../api/identityClient';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { i18n } from '../../i18n';
import { color, minInputHeight, radius, space, typography } from '../../theme/tokens';
import { isProbablyEmail } from '../SignIn/useEmailSignIn';

interface AccountRecoveryScreenProps {
  initialEmail?: string;
  onRecovered: (session: RecoverySession, email: string) => void | Promise<void>;
  onCancel: () => void;
}

/**
 * Account recovery (AC-38.5, and the "returning-user recovery" half of AC-37).
 *
 * Kept on its own screen rather than folded into sign-in because the two do
 * different things and the difference matters to the person using them. Signing
 * in adds a session. Recovery **revokes every other session on the account** --
 * which is the point when somebody else has it -- and the screen says so before
 * the customer starts, not after.
 */
export function AccountRecoveryScreen({
  initialEmail = '',
  onRecovered,
  onCancel,
}: AccountRecoveryScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const [email, setEmail] = useState(initialEmail);
  const [token, setToken] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const send = useCallback(async () => {
    const normalized = email.trim().toLowerCase();
    if (!isProbablyEmail(normalized)) {
      setErrorMessage(t('signIn.emailInvalid'));
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    try {
      await requestEmailRecovery(normalized, i18n.language === 'fr' ? 'fr' : 'en');
      setEmail(normalized);
      setSent(true);
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError
          ? error.message
          : i18n.t('errors.generic', { ns: 'auth' }),
      );
    } finally {
      setBusy(false);
    }
  }, [email, t]);

  const confirm = useCallback(async () => {
    const raw = token.trim();
    if (!raw) {
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    try {
      const session = await confirmEmailRecovery(raw);
      await onRecovered(session, email);
    } catch (error) {
      setToken('');
      setErrorMessage(
        error instanceof ApiError &&
          (error.code === 'identity_token_expired' ||
            error.code === 'identity_token_invalid')
          ? t('signIn.linkExpired')
          : error instanceof ApiError
            ? error.message
            : i18n.t('errors.generic', { ns: 'auth' }),
      );
    } finally {
      setBusy(false);
    }
  }, [email, onRecovered, t, token]);

  return (
    <KeyboardAvoidingView
      behavior={RNPlatform.OS === 'ios' ? 'padding' : undefined}
      style={styles.screen}
    >
      <ScrollView contentContainerStyle={styles.content}>
        <Text style={styles.title}>{t('recovery.title')}</Text>
        <Text style={styles.subtitle}>
          {t('recovery.subtitle', { email: email || t('signIn.emailPlaceholder') })}
        </Text>

        {sent ? (
          <StateMessage
            variant="pending"
            title={t('signIn.checkTitle')}
            body={t('recovery.sent')}
            footnote={t('signIn.checkFootnote')}
            testID="recovery-sent"
          />
        ) : (
          <>
            <Text style={styles.label}>{t('signIn.emailLabel')}</Text>
            <TextInput
              testID="recovery-email-input"
              value={email}
              onChangeText={setEmail}
              placeholder={t('signIn.emailPlaceholder')}
              placeholderTextColor={color.gray500}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              accessibilityLabel={t('signIn.emailLabel')}
              style={styles.input}
            />
          </>
        )}

        {errorMessage ? (
          <Banner tone="error" message={errorMessage} testID="recovery-error" />
        ) : null}

        {sent ? (
          <View style={styles.group}>
            <Text style={styles.label}>{t('signIn.pasteLabel')}</Text>
            <TextInput
              testID="recovery-token-input"
              value={token}
              onChangeText={setToken}
              autoCapitalize="none"
              autoCorrect={false}
              accessibilityLabel={t('signIn.pasteLabel')}
              style={styles.input}
            />
            <PrimaryButton
              testID="recovery-confirm"
              label={t('signIn.pasteAction')}
              onPress={confirm}
              disabled={busy || token.trim().length === 0}
              loading={busy}
            />
          </View>
        ) : (
          <PrimaryButton
            testID="recovery-send"
            label={t('recovery.send')}
            onPress={send}
            disabled={busy}
            loading={busy}
          />
        )}

        <SecondaryButton
          testID="recovery-cancel"
          label={t('recovery.back')}
          onPress={onCancel}
        />
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.gray50 },
  content: { padding: space.space5, gap: space.space4 },
  group: { gap: space.space3 },
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
});
