import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { ServiceSummary, ServiceState } from '../../api/consumerClient';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { StatusPill } from '../../components/StatusPill/StatusPill';
import { color, radius, space, typography } from '../../theme/tokens';

interface ConsumerHomeScreenProps {
  serviceState: ServiceState;
  services: ServiceSummary[];
  loading: boolean;
  errorMessage: string | null;
  onRetry: () => void;
  onBrowsePlans: () => void;
  onOpenMyLine: () => void;
  onOpenOrder: (orderId: string) => void;
}

/**
 * Home (AC-37.1, AC-37.5).
 *
 * The screen's whole job is to make the account's current state legible and to
 * put exactly one next action next to it. Every state below has one, including
 * the failures — a customer whose provisioning failed must not land on a screen
 * whose only content is that it failed.
 *
 * Notice what is *not* here: a spinner standing in for provisioning. Setting up
 * a line takes minutes, and a spinner held for four minutes reads as a hang.
 * `StateMessage`'s `pending` variant says what happened, what is happening, and
 * that the app need not stay open.
 */
export function ConsumerHomeScreen({
  serviceState,
  services,
  loading,
  errorMessage,
  onRetry,
  onBrowsePlans,
  onOpenMyLine,
  onOpenOrder,
}: ConsumerHomeScreenProps): React.JSX.Element {
  const { t } = useTranslation('consumer');

  if (errorMessage) {
    return (
      <ScrollView contentContainerStyle={styles.screen}>
        <StateMessage
          variant="error"
          title={t('home.loadError')}
          body={errorMessage}
          actionLabel={t('home.retry')}
          onAction={onRetry}
          busy={loading}
          testID="home-error"
        />
      </ScrollView>
    );
  }

  const headline = headlineFor(services, serviceState);

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="consumer-home">
      <Text style={styles.title}>{t('home.greeting')}</Text>

      {headline.kind === 'none' ? (
        <StateMessage
          variant="empty"
          title={t('home.noServiceTitle')}
          body={t('home.noServiceBody')}
          actionLabel={t('home.noServiceAction')}
          onAction={onBrowsePlans}
          testID="home-no-service"
        />
      ) : headline.kind === 'install' ? (
        <StateMessage
          variant="pending"
          title={t('home.installTitle')}
          body={t('home.installBody')}
          actionLabel={t('home.installAction')}
          onAction={onOpenMyLine}
          testID="home-install"
        />
      ) : headline.kind === 'suspended' ? (
        <StateMessage
          variant="blocked"
          title={t('home.suspendedTitle')}
          body={t('home.suspendedBody')}
          actionLabel={t('home.suspendedAction')}
          onAction={onOpenMyLine}
          testID="home-suspended"
        />
      ) : headline.kind === 'failed' ? (
        <StateMessage
          variant="error"
          title={t('home.failedTitle')}
          body={t('home.failedBody')}
          actionLabel={t('home.failedAction')}
          onAction={() => onOpenOrder(headline.service.order_id)}
          testID="home-failed"
        />
      ) : headline.kind === 'expired' ? (
        <StateMessage
          variant="blocked"
          title={t('home.expiredTitle')}
          body={t('home.expiredBody')}
          actionLabel={t('home.expiredAction')}
          onAction={onBrowsePlans}
          testID="home-expired"
        />
      ) : headline.kind === 'pending' ? (
        <StateMessage
          variant="pending"
          title={t('home.pendingTitle')}
          body={t('home.pendingBody')}
          footnote={t('home.pendingFootnote')}
          actionLabel={t('home.pendingAction')}
          onAction={() => onOpenOrder(headline.service.order_id)}
          testID="home-pending"
        />
      ) : null}

      {services.length > 0 ? (
        <View style={styles.list}>
          <Text style={styles.sectionTitle}>{t('home.serviceListTitle')}</Text>
          {services.map(service => (
            <ServiceCard
              key={service.order_item_id}
              service={service}
              onPress={() => onOpenOrder(service.order_id)}
            />
          ))}
        </View>
      ) : null}
    </ScrollView>
  );
}

function ServiceCard({
  service,
  onPress,
}: {
  service: ServiceSummary;
  onPress: () => void;
}): React.JSX.Element {
  const { t } = useTranslation('consumer');
  return (
    <View
      style={styles.card}
      testID={`service-card-${service.order_item_id}`}
      accessible
      accessibilityRole="summary"
      accessibilityLabel={`${service.product_name}. ${ownerLabel(service, t)}. ${
        service.ready_to_use ? t('home.readyLabel') : t('home.notReadyLabel')
      }`}
      onTouchEnd={onPress}
    >
      <View style={styles.cardHeader}>
        <Text style={styles.cardTitle}>{service.product_name}</Text>
        <StatusPill
          // "Service" is the question this pill answers -- the aggregate of
          // installation and activation, not either one on its own. My Line
          // (chunk 20) shows those separately, where the distinction is
          // actionable.
          family={t('home.serviceListTitle')}
          tone={service.ready_to_use ? 'positive' : 'caution'}
          label={
            service.ready_to_use
              ? t('home.readyLabel')
              : t('home.notReadyLabel')
          }
          testID={`service-card-${service.order_item_id}-status`}
        />
      </View>
      {/*
        One composed string rather than three children: the delivery label says
        which kind of service this is, so an internet-calling grant is never
        mistaken for an eSIM the customer forgot to install, and it has to read
        as one sentence to a screen reader rather than three fragments.
      */}
      <Text style={styles.cardMeta}>{`${ownerLabel(service, t)} · ${
        service.delivery === 'internet'
          ? t('home.deliveryInternet')
          : t('home.deliveryCarrier')
      }`}</Text>
    </View>
  );
}

function ownerLabel(
  service: ServiceSummary,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  return service.owner === 'organization'
    ? t('home.organizationLabel', {
        organization: service.organization_name ?? '',
      })
    : t('home.personalLabel');
}

type Headline =
  | { kind: 'none' }
  | { kind: 'ready'; service: ServiceSummary }
  | {
      kind: 'pending' | 'install' | 'suspended' | 'expired' | 'failed';
      service: ServiceSummary;
    };

/**
 * Which single state Home leads with.
 *
 * Ordered by what the customer can *act on*, not by severity. Somebody with an
 * installable line and an unrelated failed order should be shown the install
 * step, because that is the one that gets them connected.
 */
function headlineFor(
  services: ServiceSummary[],
  serviceState: ServiceState,
): Headline {
  if (services.length === 0) {
    return { kind: 'none' };
  }
  const installable = services.find(
    service =>
      !service.expired &&
      service.requires_installation &&
      !service.ready_to_use &&
      service.provisioning_state === 'provisioned' &&
      service.activation_state !== 'suspended',
  );
  if (installable) {
    return { kind: 'install', service: installable };
  }
  const suspended = services.find(
    service => service.activation_state === 'suspended',
  );
  if (suspended) {
    return { kind: 'suspended', service: suspended };
  }
  const ready = services.find(service => service.ready_to_use);
  if (ready) {
    return { kind: 'ready', service: ready };
  }
  const provisioning = services.find(
    service =>
      !service.expired &&
      !['failed', 'cancelled'].includes(service.provisioning_state),
  );
  if (provisioning) {
    return { kind: 'pending', service: provisioning };
  }
  const failed = services.find(service =>
    ['failed', 'cancelled'].includes(service.provisioning_state),
  );
  if (failed) {
    return { kind: 'failed', service: failed };
  }
  const expired = services.find(service => service.expired);
  if (expired) {
    return { kind: 'expired', service: expired };
  }
  // Unreachable given the branches above, but `serviceState` is the server's
  // own answer and deferring to it beats inventing one here.
  return serviceState === 'none'
    ? { kind: 'none' }
    : { kind: 'pending', service: services[0] };
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
