import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { StyleSheet, View } from 'react-native';
import {
  getConsumerSession,
  getServices,
  type ConsumerSession,
  type ServiceSummary,
} from '../api/consumerClient';
import { ApiError } from '../api/http';
import { PlaceholderScreen } from '../screens/Placeholder/PlaceholderScreen';
import { ConsumerHomeScreen } from '../screens/ConsumerHome/ConsumerHomeScreen';
import { InvitationScreen } from '../screens/Invitation/InvitationScreen';
import { MyLineFlow } from '../screens/MyLine/MyLineFlow';
import { PurchaseFlow } from '../screens/Purchase/PurchaseFlow';
import {
  clearPendingLink,
  loadPendingLink,
  subscribeToDeepLinks,
  type PendingLink,
} from '../services/deepLinks';
import { color } from '../theme/tokens';
import { TabBar, type TabDefinition } from './TabBar';

export type ConsumerTab = 'home' | 'plans' | 'my-line' | 'account';

interface ConsumerAppProps {
  accessToken: string;
  currentUserId: string;
  /** Shown when an invitation turns out to be for a different address. */
  currentEmail: string | null;
  /** Sign out and return to sign-in, optionally pre-filling an address. */
  onSwitchAccount: (emailHint?: string) => void;
}

/**
 * The authenticated host: four tabs, plus the deep-link intents that interrupt
 * them (AC-37.1, AC-37.2, AC-37.3).
 *
 * Two things it is careful about.
 *
 * **A pending link is read on mount, not only on the event.** The link that
 * sent the customer to sign in was persisted before authentication and is still
 * on disk; if this only listened for new `url` events, that link would be
 * silently dropped at the exact moment it finally became actionable.
 *
 * **The invitation screen is a modal over the tabs, not a tab.** Dismissing it
 * returns to whichever tab the customer was on, and clears the pending link so
 * the same invitation does not reappear on every foreground.
 */
export function ConsumerApp({
  accessToken,
  currentUserId,
  currentEmail,
  onSwitchAccount,
}: ConsumerAppProps): React.JSX.Element {
  const { t } = useTranslation('consumer');
  const [tab, setTab] = useState<ConsumerTab>('home');
  const [session, setSession] = useState<ConsumerSession | null>(null);
  const [services, setServices] = useState<ServiceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pendingLink, setPendingLink] = useState<PendingLink | null>(null);
  /**
   * An order the customer asked for by name — from Home's "see order status", or
   * from an `damdam://orders/:id` link. Held here rather than inside the
   * purchase flow because both routes arrive at the host, and the flow needs to
   * be told which order to open rather than having to guess from storage.
   */
  const [requestedOrderId, setRequestedOrderId] = useState<string | null>(null);
  /**
   * A line the customer asked for by name — from Home's "install now", or from
   * an order screen once the service is provisioned. Held here for the same
   * reason as the order id: both routes arrive at the host, and the flow is told
   * which line to open rather than guessing.
   */
  const [requestedLineId, setRequestedLineId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const [nextSession, nextServices] = await Promise.all([
        getConsumerSession(accessToken),
        getServices(accessToken),
      ]);
      setSession(nextSession);
      setServices(nextServices.services);
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('home.unavailableBody'),
      );
    } finally {
      setLoading(false);
    }
  }, [accessToken, t]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    // The link that arrived before there was a session to act on it.
    loadPendingLink()
      .then(link => link && setPendingLink(link))
      .catch(() => undefined);
    return subscribeToDeepLinks(
      setPendingLink,
      link => link.kind !== 'email-login' && link.kind !== 'email-recovery',
    );
  }, []);

  const dismissLink = useCallback(() => {
    setPendingLink(null);
    clearPendingLink().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (pendingLink?.kind !== 'order') {
      return;
    }
    // An order link is not a modal like an invitation: it is a request to look
    // at a purchase the customer already made, and the app has a tab for that.
    // Consumed here rather than during render so the link is cleared exactly
    // once.
    setRequestedOrderId(pendingLink.orderId);
    setTab('plans');
    dismissLink();
  }, [dismissLink, pendingLink]);

  const tabs = useMemo<TabDefinition<ConsumerTab>[]>(
    () => [
      { key: 'home', label: t('tabs.home') },
      { key: 'plans', label: t('tabs.plans') },
      { key: 'my-line', label: t('tabs.myLine') },
      {
        key: 'account',
        label: t('tabs.account'),
        badgeCount: session?.pending_invitations ?? 0,
        accessibilityLabel: session?.pending_invitations
          ? t('tabs.accountWithInvitations', {
              count: session.pending_invitations,
            })
          : t('tabs.account'),
      },
    ],
    [session?.pending_invitations, t],
  );

  if (pendingLink?.kind === 'invitation') {
    return (
      <InvitationScreen
        accessToken={accessToken}
        token={pendingLink.token}
        currentEmail={currentEmail ?? session?.verified_emails[0] ?? null}
        onAccepted={load}
        onDismiss={dismissLink}
        onSwitchAccount={hint => {
          // The link stays on disk deliberately: the customer is about to sign
          // in as the invited address, and this is the intent they will come
          // back to.
          setPendingLink(null);
          onSwitchAccount(hint);
        }}
      />
    );
  }

  return (
    <View style={styles.host}>
      <View style={styles.content}>
        {tab === 'home' ? (
          <ConsumerHomeScreen
            serviceState={session?.service_state ?? 'none'}
            services={services}
            loading={loading}
            errorMessage={errorMessage}
            onRetry={load}
            onBrowsePlans={() => setTab('plans')}
            onOpenMyLine={entitlementId => {
              setRequestedLineId(entitlementId);
              setTab('my-line');
            }}
            onOpenOrder={orderId => {
              setRequestedOrderId(orderId);
              setTab('plans');
            }}
          />
        ) : tab === 'plans' ? (
          <PurchaseFlow
            accessToken={accessToken}
            userId={currentUserId}
            initialOrderId={requestedOrderId}
            onOrderOpened={() => setRequestedOrderId(null)}
            onPurchaseSettled={load}
            onOpenMyLine={() => setTab('my-line')}
          />
        ) : tab === 'my-line' ? (
          <MyLineFlow
            accessToken={accessToken}
            initialEntitlementId={requestedLineId}
            onEntitlementOpened={() => setRequestedLineId(null)}
            onBrowsePlans={() => setTab('plans')}
            onLineChanged={load}
          />
        ) : (
          <PlaceholderScreen
            title={t('placeholder.accountTitle')}
            note={`${t('placeholder.accountBody')} ${t('placeholder.owner', {
              chunk: 21,
            })}`}
          />
        )}
      </View>
      <TabBar tabs={tabs} active={tab} onSelect={setTab} />
    </View>
  );
}

const styles = StyleSheet.create({
  host: { flex: 1, backgroundColor: color.gray50 },
  content: { flex: 1 },
});
