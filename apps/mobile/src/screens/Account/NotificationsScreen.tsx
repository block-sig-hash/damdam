import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import {
  isEnabled,
  type NotificationCategory,
  type NotificationChannel,
  type NotificationPreference,
} from '../../api/accountClient';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface NotificationsScreenProps {
  preferences: NotificationPreference[];
  busy: boolean;
  errorMessage: string | null;
  onChange: (
    category: NotificationCategory,
    channel: NotificationChannel,
    enabled: boolean,
  ) => void;
  onBack: () => void;
}

/** The three things this product sends, and nowhere to add a fourth by accident. */
const CATEGORIES: NotificationCategory[] = ['low_balance', 'expiry', 'order_status'];
const CHANNELS: NotificationChannel[] = ['push', 'email', 'sms'];

/**
 * What we tell you about (US-38, chunk 21).
 *
 * The switches read through `isEnabled`, which treats an **absent** preference
 * as the default rather than as off. That distinction is the whole reason the
 * server returns only decisions: a screen that rendered "no row" as "off" would
 * show a new customer every switch turned off, and the first thing they touched
 * would save a decision they never made.
 *
 * The intro line says plainly that turning something off does not stop the
 * service working — otherwise the honest reading of "when your balance is
 * running low" being off is that the line stops quietly.
 */
export function NotificationsScreen({
  preferences,
  busy,
  errorMessage,
  onChange,
  onBack,
}: NotificationsScreenProps) {
  const { t } = useTranslation('account');

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      testID="notifications-screen"
    >
      <Text style={styles.title} accessibilityRole="header">
        {t('sections.notifications')}
      </Text>
      <Text style={styles.body}>{t('notifications.intro')}</Text>

      {errorMessage ? (
        <Text style={styles.error} accessibilityRole="alert">
          {errorMessage}
        </Text>
      ) : null}

      {CATEGORIES.map(category => (
        <View key={category} style={styles.card}>
          <Text style={styles.sectionTitle}>
            {t(`notifications.categories.${category}`)}
          </Text>
          {CHANNELS.map(channel => {
            const enabled = isEnabled(preferences, category, channel);
            return (
              <View key={channel} style={styles.row}>
                <Text style={styles.body}>{t(`notifications.channels.${channel}`)}</Text>
                <Switch
                  value={enabled}
                  disabled={busy}
                  onValueChange={next => onChange(category, channel, next)}
                  accessibilityLabel={`${t(
                    `notifications.categories.${category}`,
                  )} — ${t(`notifications.channels.${channel}`)}`}
                  testID={`pref-${category}-${channel}`}
                />
              </View>
            );
          })}
        </View>
      ))}

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
    gap: space.space3,
  },
  sectionTitle: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.space3,
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
