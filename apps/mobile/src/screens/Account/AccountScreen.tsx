import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { DeviceSession, Receipt, SupportRequest } from '../../api/accountClient';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface AccountScreenProps {
  displayName: string;
  phoneNumber: string | null;
  email: string | null;
  sessions: DeviceSession[];
  receipts: Receipt[];
  supportRequests: SupportRequest[];
  /** When this content was last fetched. Null while nothing has loaded yet. */
  observedAt: string | null;
  /** True when what is on screen came from disk rather than the network. */
  offline: boolean;
  onOpenDevices: () => void;
  onOpenReceipts: () => void;
  onOpenSupport: () => void;
  onOpenNotifications: () => void;
  onOpenPrivacy: () => void;
}

/**
 * The account area's front page (US-38, chunk 21).
 *
 * A list of doors with a count on each, and one property worth defending: when
 * the content came from disk, the screen **says so and says when**. A cached
 * receipt list rendered identically to a live one is a customer told that a
 * refund they are waiting for has not arrived, by a screen that has not looked.
 *
 * The counts are deliberately of *active* things — signed-in devices, open
 * tickets — because a badge counting revoked devices is a badge nobody can act
 * on.
 */
export function AccountScreen({
  displayName,
  phoneNumber,
  email,
  sessions,
  receipts,
  supportRequests,
  observedAt,
  offline,
  onOpenDevices,
  onOpenReceipts,
  onOpenSupport,
  onOpenNotifications,
  onOpenPrivacy,
}: AccountScreenProps) {
  const { t } = useTranslation('account');
  const activeDevices = sessions.filter(session => session.revoked_at === null);
  const openRequests = supportRequests.filter(
    request => request.state === 'open' || request.state === 'acknowledged',
  );

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      testID="account-screen"
    >
      <Text style={styles.title} accessibilityRole="header">
        {t('title')}
      </Text>

      {offline ? (
        <View style={styles.offline} accessibilityRole="alert" testID="account-offline">
          <Text style={styles.offlineTitle}>{t('errors.offlineTitle')}</Text>
          <Text style={styles.offlineBody}>{t('errors.offlineBody')}</Text>
          {observedAt ? (
            <Text style={styles.offlineBody} testID="account-observed-at">
              {observedAt}
            </Text>
          ) : null}
        </View>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('sections.profile')}</Text>
        <Text style={styles.name}>{displayName}</Text>
        {phoneNumber ? <Text style={styles.detail}>{phoneNumber}</Text> : null}
        {email ? <Text style={styles.detail}>{email}</Text> : null}
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('sections.devices')}</Text>
        <Text style={styles.detail} testID="account-device-count">
          {String(activeDevices.length)}
        </Text>
        <SecondaryButton
          label={t('sections.devices')}
          onPress={onOpenDevices}
          testID="open-devices"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('sections.receipts')}</Text>
        <Text style={styles.detail} testID="account-receipt-count">
          {String(receipts.length)}
        </Text>
        <SecondaryButton
          label={t('sections.receipts')}
          onPress={onOpenReceipts}
          testID="open-receipts"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('sections.support')}</Text>
        <Text style={styles.detail} testID="account-open-request-count">
          {String(openRequests.length)}
        </Text>
        <SecondaryButton
          label={t('sections.support')}
          onPress={onOpenSupport}
          testID="open-support"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('sections.notifications')}</Text>
        <SecondaryButton
          label={t('sections.notifications')}
          onPress={onOpenNotifications}
          testID="open-notifications"
        />
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('sections.privacy')}</Text>
        <SecondaryButton
          label={t('sections.privacy')}
          onPress={onOpenPrivacy}
          testID="open-privacy"
        />
      </View>
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
    gap: space.space3,
  },
  sectionTitle: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  name: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  detail: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  offline: {
    padding: space.space4,
    borderRadius: radius.card,
    backgroundColor: color.warning100,
    gap: space.space2,
  },
  offlineTitle: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  offlineBody: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
});
