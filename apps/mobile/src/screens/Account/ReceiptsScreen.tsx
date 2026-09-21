import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { Receipt } from '../../api/accountClient';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { money } from '../../utils/format';

interface ReceiptsScreenProps {
  receipts: Receipt[];
  /** True when this list came from disk. The note tells the customer so. */
  fromCache: boolean;
  onBack: () => void;
}

/**
 * Receipts (US-38, chunk 21).
 *
 * Amounts are rendered from the strings the server sent, through the shared
 * `money` formatter, and are never recomputed here. A receipt's only job is to
 * agree with what was charged; a client that re-derived a total from its lines
 * would eventually disagree with the books over a rounding rule, and the screen
 * that disagrees is the one the customer screenshots.
 *
 * An organization-paid order says so. Somebody scrolling their own receipts
 * should not have to work out why a purchase they do not remember making is in
 * their list.
 */
export function ReceiptsScreen({ receipts, fromCache, onBack }: ReceiptsScreenProps) {
  const { t } = useTranslation('account');

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      testID="receipts-screen"
    >
      <Text style={styles.title} accessibilityRole="header">
        {t('sections.receipts')}
      </Text>

      {fromCache ? (
        <Text style={styles.note} testID="receipts-offline-note">
          {t('receipts.offlineNote')}
        </Text>
      ) : null}

      {receipts.length === 0 ? (
        <Text style={styles.body} testID="receipts-empty">
          {t('receipts.empty')}
        </Text>
      ) : null}

      {receipts.map(receipt => (
        <View
          key={receipt.order_id}
          style={styles.card}
          testID={`receipt-${receipt.order_id}`}
        >
          <Text style={styles.reference}>{receipt.reference}</Text>
          <Text style={styles.detail}>
            {t('receipts.placed', { when: receipt.placed_at })}
          </Text>
          {receipt.organization_id ? (
            <Text style={styles.detail}>{t('receipts.paidFor')}</Text>
          ) : null}
          <Text style={styles.sectionTitle}>{t('receipts.lines')}</Text>
          {receipt.lines.map((line, index) => (
            <View key={`${receipt.order_id}-${index}`} style={styles.row}>
              <Text style={styles.body}>{line.description}</Text>
              <Text style={styles.body}>
                {money(line.total_amount, receipt.currency)}
              </Text>
            </View>
          ))}
          <View style={styles.row}>
            <Text style={styles.totalLabel}>{t('receipts.total')}</Text>
            <Text style={styles.total} testID={`receipt-total-${receipt.order_id}`}>
              {money(receipt.total_amount, receipt.currency)}
            </Text>
          </View>
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
    gap: space.space2,
  },
  reference: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  sectionTitle: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: space.space3,
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
  totalLabel: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  total: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  note: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
