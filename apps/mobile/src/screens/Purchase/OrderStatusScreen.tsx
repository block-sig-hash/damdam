import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { OrderResponse } from '../../api/checkoutClient';
import { Banner } from '../../components/Banner/Banner';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { StatusPill } from '../../components/StatusPill/StatusPill';
import { color, radius, space, typography } from '../../theme/tokens';
import { money } from './format';

interface OrderStatusScreenProps {
  order: OrderResponse | null;
  reference: string;
  /** Local knowledge: the customer was actually sent to the processor. */
  paymentStarted: boolean;
  loading: boolean;
  busy: boolean;
  errorMessage: string | null;
  onRefresh: () => void;
  onResumePayment: () => void;
  onOpenMyLine: () => void;
  onBrowsePlans: () => void;
  onDismiss: () => void;
}

/**
 * Where every interrupted purchase lands (US-37, AC-37.5).
 *
 * This screen is the answer to "what happened to my money", and the rule that
 * shapes it is that **it never offers to buy the same thing again**. A customer
 * whose payment succeeded but whose webhook is late, whose app was killed on the
 * way back from the processor, or whose provisioning is still running, is shown
 * this order — not a plan list with a buy button, which is how a second charge
 * happens.
 *
 * Payment and provisioning are asked separately, because they fail separately.
 * "Paid" and "set up" are two different sentences here, and an order can sit
 * truthfully in the gap between them for minutes.
 */
export function OrderStatusScreen({
  order,
  reference,
  paymentStarted,
  loading,
  busy,
  errorMessage,
  onRefresh,
  onResumePayment,
  onOpenMyLine,
  onBrowsePlans,
  onDismiss,
}: OrderStatusScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');

  if (order === null) {
    return (
      <ScrollView contentContainerStyle={styles.screen} testID="order-loading">
        <Text style={styles.title}>
          {reference ? t('order.titleWithReference', { reference }) : t('order.title')}
        </Text>
        <StateMessage
          variant={errorMessage ? 'error' : 'pending'}
          title={errorMessage ? t('order.loadErrorTitle') : t('order.loadingTitle')}
          body={errorMessage ?? t('order.loadingBody')}
          actionLabel={t('order.refresh')}
          onAction={onRefresh}
          busy={loading}
          testID="order-loading-state"
        />
      </ScrollView>
    );
  }

  const headline = headlineFor(order, paymentStarted);

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="order-status">
      <Text style={styles.title}>
        {t('order.titleWithReference', { reference: order.reference })}
      </Text>
      <Text style={styles.total} testID="order-total">
        {money(order.total_amount, order.currency)}
      </Text>

      {headline === 'declined' ? (
        <StateMessage
          variant="error"
          title={t('order.declinedTitle')}
          body={t('order.declinedBody')}
          actionLabel={t('order.declinedAction')}
          onAction={onResumePayment}
          busy={busy}
          secondaryActionLabel={t('order.abandon')}
          onSecondaryAction={onDismiss}
          testID="order-declined"
        />
      ) : headline === 'unpaid' ? (
        <StateMessage
          variant="blocked"
          title={t('order.unpaidTitle')}
          body={t('order.unpaidBody')}
          actionLabel={t('order.unpaidAction')}
          onAction={onResumePayment}
          busy={busy}
          secondaryActionLabel={t('order.abandon')}
          onSecondaryAction={onDismiss}
          testID="order-unpaid"
        />
      ) : headline === 'confirming' ? (
        /*
          The delayed-webhook case. The order is `unpaid` because nothing has
          told us otherwise, and the customer has been to the processor — so the
          honest sentence is "we are confirming", and the only action is to look
          again. Offering "pay" here is offering to pay twice.
        */
        <StateMessage
          variant="pending"
          title={t('order.confirmingTitle')}
          body={t('order.confirmingBody')}
          footnote={t('order.confirmingFootnote')}
          actionLabel={t('order.refresh')}
          onAction={onRefresh}
          busy={loading}
          testID="order-confirming"
        />
      ) : headline === 'provisioning' ? (
        <StateMessage
          variant="pending"
          title={t('order.provisioningTitle')}
          body={t('order.provisioningBody')}
          footnote={t('order.provisioningFootnote')}
          actionLabel={t('order.refresh')}
          onAction={onRefresh}
          busy={loading}
          testID="order-provisioning"
        />
      ) : headline === 'unknown' ? (
        /*
          `outcome_unknown` is a supplier request whose answer was lost. It is
          reconciled against the original operation reference and never retried
          as a fresh purchase, so there is nothing for the customer to do and
          saying "try again" would be inviting a duplicate line.
        */
        <StateMessage
          variant="pending"
          title={t('order.unknownTitle')}
          body={t('order.unknownBody')}
          actionLabel={t('order.refresh')}
          onAction={onRefresh}
          busy={loading}
          testID="order-unknown"
        />
      ) : headline === 'failed' ? (
        <StateMessage
          variant="error"
          title={t('order.provisioningFailedTitle')}
          body={t('order.provisioningFailedBody')}
          actionLabel={t('order.contactSupport')}
          onAction={onOpenMyLine}
          testID="order-provisioning-failed"
        />
      ) : headline === 'refunded' ? (
        <StateMessage
          variant="blocked"
          title={t('order.refundedTitle')}
          body={t('order.refundedBody')}
          actionLabel={t('order.browsePlans')}
          onAction={onBrowsePlans}
          testID="order-refunded"
        />
      ) : (
        <StateMessage
          variant="empty"
          title={t('order.readyTitle')}
          body={t('order.readyBody')}
          actionLabel={t('order.readyAction')}
          onAction={onOpenMyLine}
          testID="order-ready"
        />
      )}

      {errorMessage ? (
        <Banner tone="error" testID="order-error" message={errorMessage} />
      ) : null}

      <View style={styles.list}>
        <Text style={styles.sectionTitle}>{t('order.itemsTitle')}</Text>
        {order.items.map(item => (
          <View
            key={item.order_item_id}
            style={styles.card}
            testID={`order-item-${item.order_item_id}`}
          >
            <View style={styles.cardHeader}>
              <Text style={styles.cardTitle}>{item.product_name}</Text>
              <StatusPill
                family={t('order.itemsTitle')}
                tone={
                  item.provisioning_state === 'provisioned'
                    ? 'positive'
                    : ['failed', 'cancelled'].includes(item.provisioning_state)
                      ? 'negative'
                      : 'caution'
                }
                label={t(`order.provisioningState.${item.provisioning_state}`, {
                  defaultValue: t('order.provisioningState.not_started'),
                })}
                testID={`order-item-${item.order_item_id}-status`}
              />
            </View>
            <Text style={styles.cardMeta}>
              {money(item.unit_amount, item.unit_currency)}
            </Text>
          </View>
        ))}
      </View>

      <SecondaryButton
        label={t('order.done')}
        onPress={onDismiss}
        testID="order-done"
      />
    </ScrollView>
  );
}

type Headline =
  | 'declined'
  | 'unpaid'
  | 'confirming'
  | 'provisioning'
  | 'unknown'
  | 'failed'
  | 'refunded'
  | 'ready';

/**
 * Money first, then fulfilment.
 *
 * The order matters: an order whose payment failed has nothing useful to say
 * about provisioning, and an order that is paid must never fall through to a
 * branch that offers to pay. `paymentStarted` is the only thing that separates
 * "you have not paid yet" from "we are confirming your payment", and it is local
 * knowledge precisely because the server cannot distinguish them either — both
 * look like an unpaid order with an open attempt.
 */
export function headlineFor(
  order: OrderResponse,
  paymentStarted: boolean,
): Headline {
  if (order.payment_state === 'failed') {
    return 'declined';
  }
  if (order.payment_state === 'refunded') {
    return 'refunded';
  }
  if (order.payment_state === 'unpaid') {
    return paymentStarted ? 'confirming' : 'unpaid';
  }
  // `authorized` and `paid` both mean the customer is done with the payment
  // screen; what is left is fulfilment.
  if (order.fulfilment_state === 'provisioned') {
    return 'ready';
  }
  if (order.fulfilment_state === 'outcome_unknown') {
    return 'unknown';
  }
  if (order.fulfilment_state === 'failed' || order.fulfilment_state === 'cancelled') {
    return 'failed';
  }
  return 'provisioning';
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
  total: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  sectionTitle: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.gray900,
  },
  list: { gap: space.space3 },
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
    alignItems: 'center',
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
  cardMeta: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
});
