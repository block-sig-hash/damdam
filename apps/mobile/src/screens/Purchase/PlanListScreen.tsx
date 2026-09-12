import React from 'react';
import { useTranslation } from 'react-i18next';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { MarketSummary, ProductSummary } from '../../api/checkoutClient';
import { Banner } from '../../components/Banner/Banner';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import type { DeviceCheck } from './deviceFacts';
import { dataAllowance, money, voiceAllowance } from './format';

interface PlanListScreenProps {
  markets: MarketSummary[];
  market: MarketSummary | null;
  products: ProductSummary[];
  device: DeviceCheck;
  loading: boolean;
  errorMessage: string | null;
  busyProductId: string | null;
  onSelectMarket: (market: MarketSummary) => void;
  onChoose: (product: ProductSummary) => void;
  onConfirmEsimCapable: () => void;
  onRetry: () => void;
}

/**
 * Browsing (US-37, AC-37.4).
 *
 * The screen's rule is that **nothing is hidden**. A plan this phone cannot take
 * is rendered with its price, its contents and the reason it is unavailable,
 * because a customer who watches a plan disappear learns nothing and a customer
 * told "this phone cannot take an eSIM" can go and check. Hiding is also how a
 * catalog quietly becomes a lie: the plan exists, it is for sale, and the
 * obstacle is on this side of the transaction.
 *
 * Everything the chunk requires before payment is on the card — full price and
 * currency, what the plan includes, the number policy, and which destinations
 * its tariff actually prices. Not because a card is the ideal place for all of
 * it, but because the alternative is a customer discovering at the receipt that
 * the plan they bought has no number.
 */
export function PlanListScreen({
  markets,
  market,
  products,
  device,
  loading,
  errorMessage,
  busyProductId,
  onSelectMarket,
  onChoose,
  onConfirmEsimCapable,
  onRetry,
}: PlanListScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');

  if (errorMessage) {
    return (
      <ScrollView contentContainerStyle={styles.screen}>
        <StateMessage
          variant="error"
          title={t('plans.loadErrorTitle')}
          body={errorMessage}
          actionLabel={t('plans.retry')}
          onAction={onRetry}
          busy={loading}
          testID="plans-error"
        />
      </ScrollView>
    );
  }

  if (!loading && markets.length === 0) {
    return (
      <ScrollView contentContainerStyle={styles.screen}>
        <StateMessage
          variant="empty"
          title={t('plans.noMarketTitle')}
          body={t('plans.noMarketBody')}
          testID="plans-no-market"
        />
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="plan-list">
      <Text style={styles.title}>{t('plans.title')}</Text>

      {markets.length > 1 ? (
        <View style={styles.markets} testID="plans-markets">
          {markets.map(candidate => {
            const active =
              candidate.country === market?.country &&
              candidate.currency === market?.currency;
            return (
              <Pressable
                key={`${candidate.country}-${candidate.currency}`}
                testID={`market-${candidate.country}-${candidate.currency}`}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                onPress={() => onSelectMarket(candidate)}
                style={[styles.marketChip, active && styles.marketChipActive]}
              >
                <Text style={[styles.marketLabel, active && styles.marketLabelActive]}>
                  {`${candidate.country} · ${candidate.currency}`}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}

      {market ? (
        <Text style={styles.seller} testID="plans-seller">
          {t('plans.soldBy', { seller: market.seller_name })}
        </Text>
      ) : null}

      {/*
        Guidance, never a verdict. The eSIM banner says what was checked, admits
        the check can be wrong, and tells the customer the two things they can
        look at themselves — which is the only honest way to offer a way past a
        heuristic. The lock banner has no check behind it at all and says so.
      */}
      {device.reportedIncapable ? (
        <Banner
          tone="warning"
          testID="device-incapable"
          message={t('plans.deviceIncapable', { model: device.model ?? '' })}
          actionLabel={t('plans.deviceConfirm')}
          onAction={onConfirmEsimCapable}
        />
      ) : device.source === 'customer' ? (
        <Banner
          tone="info"
          testID="device-customer-confirmed"
          message={t('plans.deviceCustomerConfirmed')}
        />
      ) : null}
      <Banner
        tone="info"
        testID="device-lock-guidance"
        message={t('plans.lockGuidance')}
      />

      {products.length === 0 && !loading ? (
        <StateMessage
          variant="empty"
          title={t('plans.noPlansTitle')}
          body={t('plans.noPlansBody')}
          testID="plans-empty"
        />
      ) : null}

      {products.map(product => (
        <PlanCard
          key={product.product_id}
          product={product}
          busy={busyProductId === product.product_id}
          disabled={busyProductId !== null}
          onChoose={() => onChoose(product)}
        />
      ))}
    </ScrollView>
  );
}

function PlanCard({
  product,
  busy,
  disabled,
  onChoose,
}: {
  product: ProductSummary;
  busy: boolean;
  disabled: boolean;
  onChoose: () => void;
}): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const data = dataAllowance(product.data_bytes);
  const voiceMinutes = voiceAllowance(product.voice_seconds);
  const includes = [
    data ? t('plans.includesData', { amount: data }) : null,
    voiceMinutes ? t('plans.includesVoice', { minutes: voiceMinutes }) : null,
  ].filter((line): line is string => line !== null);

  return (
    <View style={styles.card} testID={`plan-${product.product_id}`}>
      <View style={styles.cardHeader}>
        <Text style={styles.cardTitle}>{product.name}</Text>
        <Text style={styles.price} testID={`plan-${product.product_id}-price`}>
          {money(product.amount, product.currency)}
        </Text>
      </View>

      <Text style={styles.detail} testID={`plan-${product.product_id}-includes`}>
        {includes.length > 0 ? includes.join(' · ') : t('plans.includesNothing')}
      </Text>

      {product.validity_days ? (
        <Text style={styles.detail}>
          {t('plans.validity', { days: product.validity_days })}
        </Text>
      ) : null}

      {/*
        The number policy is on the card because it is the detail customers are
        most often surprised by after paying: a data plan with `number_type:
        none` carries no number at all, and "assigned on activation" is not the
        same promise as a number you can give out today.
      */}
      <Text style={styles.detail} testID={`plan-${product.product_id}-number`}>
        {numberPolicyLabel(product, t)}
      </Text>

      {product.coverage_countries.length > 0 ? (
        <Text style={styles.detail}>
          {t('plans.coverage', { countries: product.coverage_countries.join(', ') })}
        </Text>
      ) : null}

      <Text style={styles.detail} testID={`plan-${product.product_id}-destinations`}>
        {product.call_destinations.length > 0
          ? t('plans.callsTo', {
              countries: product.call_destinations
                .map(destination => destination.country)
                .join(', '),
            })
          : t('plans.callsNone')}
      </Text>

      {product.device_notes ? (
        <Text style={styles.footnote}>{product.device_notes}</Text>
      ) : null}

      {product.purchasable ? (
        <PrimaryButton
          label={t('plans.choose')}
          onPress={onChoose}
          loading={busy}
          disabled={disabled && !busy}
          testID={`plan-${product.product_id}-choose`}
        />
      ) : (
        <Banner
          tone="neutral"
          testID={`plan-${product.product_id}-unavailable`}
          message={unavailableMessage(product.unavailable_reason, t)}
        />
      )}
    </View>
  );
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

function numberPolicyLabel(product: ProductSummary, t: Translate): string {
  if (product.number_type === 'none' || product.number_assignment === 'none') {
    return t('plans.numberNone');
  }
  const kind = t(`plans.numberType.${product.number_type}`, {
    defaultValue: t('plans.numberType.mobile'),
  });
  // "A new number is assigned when the line is set up" is a materially
  // different promise from "here is your number now", and the customer finds
  // out which one they bought here rather than at the receipt.
  return product.number_country
    ? t('plans.numberNewAssignedIn', {
        type: kind,
        country: product.number_country,
      })
    : t('plans.numberNewAssigned', { type: kind });
}

/**
 * The server's refusal code, said in the customer's language.
 *
 * `defaultValue` rather than a lookup that can return the raw code: a new
 * eligibility rule on the server must not surface `supplier_capability_mismatch`
 * verbatim in a plan card, and a generic sentence with a support route is a
 * better failure than a leaked identifier.
 */
function unavailableMessage(reason: string | null, t: Translate): string {
  if (!reason) {
    return t('plans.unavailable.unknown');
  }
  return t(`plans.unavailable.${reason}`, {
    defaultValue: t('plans.unavailable.unknown'),
  });
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
  markets: { flexDirection: 'row', flexWrap: 'wrap', gap: space.space2 },
  marketChip: {
    paddingVertical: space.space2,
    paddingHorizontal: space.space4,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.gray300,
    backgroundColor: color.white,
  },
  marketChipActive: {
    borderColor: color.primary500,
    backgroundColor: color.primary100,
  },
  marketLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  marketLabelActive: { color: color.primary700 },
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
    gap: space.space2,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: space.space3,
  },
  cardTitle: {
    flexShrink: 1,
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.gray900,
  },
  price: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  detail: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  footnote: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
