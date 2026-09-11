import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type {
  PaymentMethodsResponse,
  QuoteResponse,
} from '../../api/checkoutClient';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { color, radius, space, typography } from '../../theme/tokens';
import { hasExpired, minutesUntil, money } from './format';

interface QuoteReviewScreenProps {
  quote: QuoteResponse;
  methods: PaymentMethodsResponse | null;
  paying: boolean;
  errorMessage: string | null;
  /** Set when the server refused the quote itself — expired, used, tampered. */
  quoteRejected: boolean;
  onPay: () => void;
  onRequote: () => void;
  onBack: () => void;
}

/**
 * The last screen before money moves (US-37, AC-37.4).
 *
 * A quote is immutable and server-priced, so this screen renders it and does not
 * recompute any part of it — no client-side subtotal, no "you save" line, no
 * currency conversion. The number beside the pay button is the number the server
 * will charge, character for character, and the only way to keep that true is to
 * never do arithmetic on it here.
 *
 * Three things it refuses to be vague about:
 *
 * - **Expiry.** The remaining time is shown before the customer commits, and an
 *   expired quote becomes a re-price rather than a failed payment.
 * - **Tax.** A null `tax_configuration_reference` reads as "no tax has been
 *   applied", which is what is true while D3 is open. Rendering it as `0.00` tax
 *   would be a claim about a tax treatment nobody has decided.
 * - **Whether payment can be taken at all.** D3/D4 are open, so
 *   `collection_enabled` is false everywhere today. Saying so up front beats a
 *   pay button that answers 409.
 */
export function QuoteReviewScreen({
  quote,
  methods,
  paying,
  errorMessage,
  quoteRejected,
  onPay,
  onRequote,
  onBack,
}: QuoteReviewScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const expired = quoteRejected || hasExpired(quote.expires_at);
  const minutes = minutesUntil(quote.expires_at);
  const collectionBlocked = methods !== null && !methods.collection_enabled;

  if (expired) {
    return (
      <ScrollView contentContainerStyle={styles.screen}>
        <StateMessage
          variant="blocked"
          title={t('review.expiredTitle')}
          body={t('review.expiredBody')}
          actionLabel={t('review.expiredAction')}
          onAction={onRequote}
          secondaryActionLabel={t('review.back')}
          onSecondaryAction={onBack}
          testID="quote-expired"
        />
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="quote-review">
      <Text style={styles.title}>{t('review.title')}</Text>
      <Text style={styles.seller} testID="quote-seller">
        {t('review.soldBy', { seller: quote.seller_name })}
      </Text>

      <View style={styles.card}>
        {quote.items.map(item => (
          <View key={item.product_id} style={styles.line} testID={`quote-line-${item.product_id}`}>
            <Text style={styles.lineName}>
              {item.quantity > 1
                ? t('review.lineWithQuantity', {
                    name: item.product_name,
                    quantity: item.quantity,
                  })
                : item.product_name}
            </Text>
            <Text style={styles.lineAmount}>
              {money(item.line_amount, quote.currency)}
            </Text>
          </View>
        ))}

        <View style={styles.divider} />

        <Total label={t('review.subtotal')} amount={money(quote.subtotal_amount, quote.currency)} />
        {quote.fee_amount !== '0' && Number(quote.fee_amount) !== 0 ? (
          <Total label={t('review.fees')} amount={money(quote.fee_amount, quote.currency)} />
        ) : null}
        <Text style={styles.taxNote} testID="quote-tax">
          {quote.tax_configuration_reference
            ? t('review.taxApplied', {
                amount: money(quote.tax_amount, quote.currency),
                reference: quote.tax_configuration_reference,
              })
            : t('review.taxUndecided')}
        </Text>

        <View style={styles.divider} />

        <View style={styles.line}>
          <Text style={styles.totalLabel}>{t('review.total')}</Text>
          <Text style={styles.totalAmount} testID="quote-total">
            {money(quote.total_amount, quote.currency)}
          </Text>
        </View>
      </View>

      <Banner
        tone="info"
        testID="quote-expiry"
        message={
          minutes > 0
            ? t('review.expiresIn', { minutes })
            : t('review.expiresSoon')
        }
      />

      {methods?.card_fallback_required ? (
        <Text style={styles.footnote} testID="quote-methods">
          {t('review.cardOnly')}
        </Text>
      ) : null}

      {collectionBlocked ? (
        <Banner
          tone="warning"
          testID="collection-blocked"
          message={t('review.collectionBlocked')}
        />
      ) : null}

      {errorMessage ? (
        <Banner tone="error" testID="quote-error" message={errorMessage} />
      ) : null}

      {/*
        `paying` disables the button for the duration of the request. That alone
        is not the double-tap defence — a fast enough second press, or a retry
        after a lost response, still reaches the server — it is just the part the
        customer can see. The real one is that the quote is the server's
        idempotency key, so the second call returns the first order.
      */}
      <PrimaryButton
        label={t('review.pay', { amount: money(quote.total_amount, quote.currency) })}
        onPress={onPay}
        loading={paying}
        disabled={collectionBlocked}
        testID="quote-pay"
      />
      <SecondaryButton label={t('review.back')} onPress={onBack} testID="quote-back" />
    </ScrollView>
  );
}

function Total({ label, amount }: { label: string; amount: string }): React.JSX.Element {
  return (
    <View style={styles.line}>
      <Text style={styles.lineName}>{label}</Text>
      <Text style={styles.lineAmount}>{amount}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flexGrow: 1,
    padding: space.space5,
    gap: space.space4,
    backgroundColor: color.gray50,
  },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  seller: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  card: {
    padding: space.space4,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.gray200,
    backgroundColor: color.white,
    gap: space.space3,
  },
  line: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: space.space3,
  },
  lineName: {
    flexShrink: 1,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  lineAmount: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  divider: { height: 1, backgroundColor: color.gray200 },
  totalLabel: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.gray900,
  },
  totalAmount: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  taxNote: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  footnote: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
