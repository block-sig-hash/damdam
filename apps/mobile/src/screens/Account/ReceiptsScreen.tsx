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
  const { t, i18n } = useTranslation('account');

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
            {t('receipts.placed', { when: receiptDate(receipt.placed_at, i18n.language) })}
          </Text>
          {receipt.organization_id ? (
            <Text style={styles.detail}>{t('receipts.paidFor')}</Text>
          ) : null}
          <Text style={styles.sectionTitle}>{t('receipts.lines')}</Text>
          {receipt.lines.map((line, index) => (
            <View key={`${receipt.order_id}-${index}`} style={styles.row}>
              <Text style={styles.body}>{line.description}</Text>
              <Text style={styles.lineAmount}>
                {receiptMoney(line.total_amount, receipt.currency)}
              </Text>
            </View>
          ))}
          <View style={styles.row}>
            <Text style={styles.totalLabel}>{t('receipts.total')}</Text>
            <Text style={styles.total} testID={`receipt-total-${receipt.order_id}`}>
              {receiptMoney(receipt.total_amount, receipt.currency)}
            </Text>
          </View>
        </View>
      ))}

      <SecondaryButton label={t('actions.refresh')} onPress={onBack} />
    </ScrollView>
  );
}

/** Keep the server's decimal value exact; remove only redundant zeroes. */
function receiptMoney(amount: string, currency: string): string {
  const parts = /^(-?\d+)(?:\.(\d+))?$/.exec(amount);
  if (!parts) return money(amount, currency);

  let minorDigits = currency === 'NGN' ? 2 : 0;
  try {
    minorDigits = new Intl.NumberFormat('en', { style: 'currency', currency })
      .resolvedOptions().minimumFractionDigits ?? minorDigits;
  } catch {
    // An unknown currency still displays the exact amount and code.
  }
  const significant = (parts[2] ?? '').replace(/0+$/, '');
  const fraction = significant.padEnd(minorDigits, '0');
  return money(`${parts[1]}${fraction ? `.${fraction}` : ''}`, currency);
}

/** State the timezone rather than showing a raw ISO instant as customer copy. */
function receiptDate(value: string, locale: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale.startsWith('fr') ? 'fr-FR' : 'en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  }).format(date);
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
    gap: space.space1,
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
  lineAmount: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
    textAlign: 'right',
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
    textAlign: 'right',
  },
  note: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
