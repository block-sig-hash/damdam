import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { DeletionBlocker, DeletionPreflight, ExportJob } from '../../api/accountClient';
import { DestructiveButton } from '../../components/DestructiveButton/DestructiveButton';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface PrivacyScreenProps {
  preflight: DeletionPreflight | null;
  exportJob: ExportJob | null;
  busy: boolean;
  errorMessage: string | null;
  onRequestExport: () => void;
  onDelete: () => void;
  onBack: () => void;
}

/**
 * Your data: export and deletion (US-38, chunk 21).
 *
 * The whole screen turns on one rule: **when deletion cannot proceed, the
 * reasons are shown and the button is not offered.** A disabled button with no
 * explanation is the version of this screen that generates support tickets, and
 * a button that fails on press is the version that makes people try again.
 *
 * Blocker codes are localized here from a fixed map. The server sends codes
 * precisely so the app can say something specific; it does not send the internal
 * detail, because that text can name a colleague's line and this customer is not
 * entitled to it. An unrecognised code falls back to a general sentence rather
 * than rendering a raw identifier at somebody.
 *
 * Deletion is also honest about what it does not remove: receipts stay, because
 * financial records are retained regardless of the account they belonged to.
 * Saying so here is cheaper than saying it afterwards.
 */
export function PrivacyScreen({
  preflight,
  exportJob,
  busy,
  errorMessage,
  onRequestExport,
  onDelete,
  onBack,
}: PrivacyScreenProps) {
  const { t } = useTranslation('account');
  const [confirming, setConfirming] = useState(false);

  const describe = (blocker: DeletionBlocker): string => {
    if (blocker.code === 'refund_in_progress') {
      return blocker.amount && blocker.currency
        ? t('privacy.blockers.refund_in_progress', {
            amount: blocker.amount,
            currency: blocker.currency,
          })
        : t('privacy.blockers.refund_in_progress_noamount');
    }
    const known = [
      'active_service',
      'payment_in_progress',
      'organization_has_other_members',
      'call_in_progress',
      'call_settlement_pending',
      'call_unsettled',
    ];
    return known.includes(blocker.code)
      ? t(`privacy.blockers.${blocker.code}`)
      : t('privacy.blockers.unknown');
  };

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      testID="privacy-screen"
    >
      <Text style={styles.title} accessibilityRole="header">
        {t('sections.privacy')}
      </Text>

      {errorMessage ? (
        <Text style={styles.error} accessibilityRole="alert">
          {errorMessage}
        </Text>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('privacy.exportTitle')}</Text>
        <Text style={styles.body}>{t('privacy.exportBody')}</Text>
        {exportJob ? (
          <Text style={styles.body} testID="export-pending">
            {t('privacy.exportRequested')}
          </Text>
        ) : (
          <PrimaryButton
            label={t('privacy.exportAction')}
            onPress={onRequestExport}
            disabled={busy}
            testID="request-export"
          />
        )}
      </View>

      <View style={styles.card}>
        <Text style={styles.sectionTitle}>{t('privacy.deleteTitle')}</Text>
        <Text style={styles.body}>{t('privacy.deleteBody')}</Text>

        {preflight === null ? (
          <Text style={styles.body} testID="deletion-checking">
            {t('privacy.deleteChecking')}
          </Text>
        ) : preflight.may_delete ? (
          confirming ? (
            <DestructiveButton
              label={t('privacy.deleteConfirm')}
              onPress={onDelete}
              disabled={busy}
              testID="delete-confirm"
            />
          ) : (
            <DestructiveButton
              label={t('privacy.deleteAction')}
              onPress={() => setConfirming(true)}
              disabled={busy}
              testID="delete-start"
            />
          )
        ) : (
          <View style={styles.blockers} testID="deletion-blocked">
            <Text style={styles.blockerTitle}>{t('privacy.cannotDeleteTitle')}</Text>
            <Text style={styles.body}>{t('privacy.cannotDeleteBody')}</Text>
            {preflight.blockers.map((blocker, index) => (
              <Text
                key={`${blocker.code}-${index}`}
                style={styles.body}
                testID={`blocker-${blocker.code}`}
              >
                {describe(blocker)}
              </Text>
            ))}
          </View>
        )}
      </View>

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
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  blockers: {
    padding: space.space3,
    borderRadius: radius.card,
    backgroundColor: color.warning100,
    gap: space.space2,
  },
  blockerTitle: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  error: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.error700,
  },
});
