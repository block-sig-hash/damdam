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
            onOpenMyLine={() => setTab('my-line')}
            // Order detail is chunk 19's screen. Until it exists, the closest
            // truthful destination is My Line, and Home says so rather than
            // opening a screen that cannot answer the question.
            onOpenOrder={() => setTab('my-line')}
          />
        ) : tab === 'plans' ? (
          <PlaceholderScreen
            title={t('placeholder.plansTitle')}
            note={`${t('placeholder.plansBody')} ${t('placeholder.owner', {
              chunk: 19,
            })}`}
          />
        ) : tab === 'my-line' ? (
          <PlaceholderScreen
            title={t('placeholder.myLineTitle')}
            note={`${t('placeholder.myLineBody')} ${t('placeholder.owner', {
              chunk: 20,
            })}`}
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
