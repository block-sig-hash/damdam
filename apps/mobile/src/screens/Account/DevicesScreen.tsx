import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { DeviceSession } from '../../api/accountClient';
import { DestructiveButton } from '../../components/DestructiveButton/DestructiveButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface DevicesScreenProps {
  sessions: DeviceSession[];
  /** This handset, when we know which row it is. Null when we do not. */
  currentSessionId: string | null;
  busy: boolean;
  errorMessage: string | null;
  onRevoke: (sessionId: string) => void;
  onRevokeAll: (keepCurrent: boolean) => void;
  onBack: () => void;
}

/**
 * Signed-in devices (US-38, chunk 21).
 *
 * A revocation screen is only useful if its rows are distinguishable, so each
 * one leads with the label the device reported and carries where and when it was
 * last used. Where we have never seen it since sign-in, the screen says exactly
 * that instead of showing a blank or, worse, the sign-in time dressed up as
 * activity.
 *
 * **Signing out everything is two decisions, not one.** The destructive action
 * asks whether this phone is included, because the two cases are genuinely
 * different: a stolen handset means *everything*, and a suspicious login
 * elsewhere means *everything but this*. A single button has to guess, and the
 * guess that signs you out of the phone in your hand looks like the app broke.
 */
export function DevicesScreen({
  sessions,
  currentSessionId,
  busy,
  errorMessage,
  onRevoke,
  onRevokeAll,
  onBack,
}: DevicesScreenProps) {
  const { t } = useTranslation('account');
  const [confirming, setConfirming] = useState(false);
  const active = sessions.filter(session => session.revoked_at === null);

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      testID="devices-screen"
    >
      <Text style={styles.title} accessibilityRole="header">
        {t('sections.devices')}
      </Text>

      {errorMessage ? (
        <Text style={styles.error} accessibilityRole="alert">
          {errorMessage}
        </Text>
      ) : null}

      {active.length === 0 ? (
        <Text style={styles.body}>{t('devices.empty')}</Text>
      ) : null}

      {sessions.map(session => {
        const isCurrent = session.session_id === currentSessionId;
        const revoked = session.revoked_at !== null;
        return (
          <View
            key={session.session_id}
            style={styles.card}
            testID={`device-${session.session_id}`}
          >
            <Text style={styles.deviceLabel}>
              {session.device_label ?? t(`devices.platform.${session.platform}`)}
            </Text>
            {isCurrent ? (
              <Text style={styles.badge}>{t('devices.thisDevice')}</Text>
            ) : null}
            {session.last_seen_city && session.last_seen_country ? (
              <Text style={styles.detail}>
                {t('devices.location', {
                  city: session.last_seen_city,
                  country: session.last_seen_country,
                })}
              </Text>
            ) : null}
            <Text style={styles.detail}>
              {session.last_seen_at
                ? t('devices.lastSeen', { when: session.last_seen_at })
                : t('devices.lastSeenUnknown')}
            </Text>
            {revoked ? (
              <Text style={styles.detail} testID={`device-revoked-${session.session_id}`}>
                {t('devices.revoked', { when: session.revoked_at })}
              </Text>
            ) : (
              <SecondaryButton
                label={t('devices.signOut')}
                onPress={() => onRevoke(session.session_id)}
                disabled={busy}
                testID={`revoke-${session.session_id}`}
              />
            )}
          </View>
        );
      })}

      {confirming ? (
        <View style={styles.card} testID="revoke-all-confirm">
          <Text style={styles.body}>{t('devices.signOutAllConfirm')}</Text>
          <DestructiveButton
            label={t('devices.signOutAll')}
            onPress={() => onRevokeAll(false)}
            disabled={busy}
            testID="revoke-all-including-this"
          />
          <SecondaryButton
            label={t('devices.signOutAllOthers')}
            onPress={() => onRevokeAll(true)}
            disabled={busy || currentSessionId === null}
            testID="revoke-all-others"
          />
        </View>
      ) : (
        <DestructiveButton
          label={t('devices.signOutAll')}
          onPress={() => setConfirming(true)}
          disabled={busy || active.length === 0}
          testID="revoke-all"
        />
      )}

      <SecondaryButton label={t('actions.refresh')} onPress={onBack} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: color.gray50 },
  content: { padding: space.space5, gap: space.space4 },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  card: {
    padding: space.space4,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.gray200,
    backgroundColor: color.white,
    gap: space.space2,
  },
  deviceLabel: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  badge: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.primary700,
  },
  detail: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  error: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.error700,
  },
});
