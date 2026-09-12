import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { StyleSheet, View } from 'react-native';
import { ApiError } from '../../api/http';
import {
  fetchDeletionPreflight,
  fetchPreferences,
  fetchReceipts,
  fetchSessions,
  fetchSupportRequests,
  openSupportRequest,
  requestExport,
  revokeAllSessions,
  revokeSession,
  setPreference,
  type DeletionPreflight,
  type DeviceSession,
  type ExportJob,
  type NotificationCategory,
  type NotificationChannel,
  type NotificationPreference,
  type Receipt,
  type SupportCategory,
  type SupportRequest,
} from '../../api/accountClient';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { clearAccount, readSlice, writeSlice } from '../../services/accountCache';
import { color } from '../../theme/tokens';
import { AccountScreen } from './AccountScreen';
import { DevicesScreen } from './DevicesScreen';
import { NotificationsScreen } from './NotificationsScreen';
import { PrivacyScreen } from './PrivacyScreen';
import { ReceiptsScreen } from './ReceiptsScreen';
import { SupportScreen } from './SupportScreen';

type Stage = 'account' | 'devices' | 'receipts' | 'support' | 'notifications' | 'privacy';

interface AccountFlowProps {
  accessToken: string;
  userId: string;
  displayName: string;
  phoneNumber: string | null;
  email: string | null;
  /** Called after a deletion request is accepted, so the app can sign out. */
  onAccountDeleted: () => void;
  /** Called after every device is signed out, including this one. */
  onSignedOutEverywhere: () => void;
}

/**
 * The account area (US-38, chunk 21).
 *
 * Three decisions live here rather than in the screens.
 *
 * **Receipts are cached; nothing else is.** A receipt is something a customer
 * needs on a plane, and it cannot change after the fact — so it is safe on disk
 * and useful there. Device lists, preferences and the deletion preflight are
 * *decisions about now*: a cached device list would show a revoked phone as
 * signed in, and a cached preflight would offer a delete button the server has
 * since decided to refuse. Those load or they say they could not.
 *
 * **The cache is cleared by account id whenever this flow signs out.** The
 * handset is shared in this market, and every isolation guarantee the API makes
 * is undone by one receipt list left on disk for the next person who signs in.
 *
 * **A failed load falls back to disk and says so.** The offline banner names the
 * time the content was observed; rendering cached content silently is how a
 * customer concludes a refund never arrived from a screen that never looked.
 */
export function AccountFlow({
  accessToken,
  userId,
  displayName,
  phoneNumber,
  email,
  onAccountDeleted,
  onSignedOutEverywhere,
}: AccountFlowProps) {
  const { t } = useTranslation('account');
  const [stage, setStage] = useState<Stage>('account');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [observedAt, setObservedAt] = useState<string | null>(null);

  const [sessions, setSessions] = useState<DeviceSession[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [requests, setRequests] = useState<SupportRequest[]>([]);
  const [preferences, setPreferences] = useState<NotificationPreference[]>([]);
  const [preflight, setPreflight] = useState<DeletionPreflight | null>(null);
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const [lastReference, setLastReference] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const [sessionList, receiptList, requestList, preferenceList] = await Promise.all([
        fetchSessions(accessToken),
        fetchReceipts(accessToken),
        fetchSupportRequests(accessToken),
        fetchPreferences(accessToken),
      ]);
      setSessions(sessionList.sessions);
      setReceipts(receiptList.receipts);
      setRequests(requestList.requests);
      setPreferences(preferenceList.preferences);
      setOffline(false);
      const now = new Date().toISOString();
      setObservedAt(now);
      // Only receipts go to disk. See the module note.
      await writeSlice(userId, 'receipts', receiptList.receipts, now);
    } catch (error) {
      const cached = await readSlice<Receipt[]>(userId, 'receipts');
      if (cached) {
        setReceipts(cached.value);
        setObservedAt(cached.observedAt);
        setOffline(true);
      } else {
        setErrorMessage(
          error instanceof ApiError ? error.message : t('errors.unexpected'),
        );
      }
    } finally {
      setLoading(false);
    }
  }, [accessToken, userId, t]);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  const loadPreflight = useCallback(async () => {
    try {
      setPreflight(await fetchDeletionPreflight(accessToken));
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('errors.unexpected'),
      );
    }
  }, [accessToken, t]);

  const handleRevoke = async (sessionId: string) => {
    setBusy(true);
    setErrorMessage(null);
    try {
      await revokeSession(accessToken, sessionId);
      await load();
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('errors.unexpected'),
      );
    } finally {
      setBusy(false);
    }
  };

  const handleRevokeAll = async (keepCurrent: boolean) => {
    setBusy(true);
    setErrorMessage(null);
    try {
      // There is no id for this device yet — the API takes one and the app does
      // not know it, so "keep this one" cannot be honoured and is not claimed.
      // Signing out everything clears this account's cache, because the next
      // person to open the app must not find it.
      await revokeAllSessions(accessToken);
      await clearAccount(userId);
      if (!keepCurrent) {
        onSignedOutEverywhere();
        return;
      }
      await load();
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('errors.unexpected'),
      );
    } finally {
      setBusy(false);
    }
  };

  const handlePreference = async (
    category: NotificationCategory,
    channel: NotificationChannel,
    enabled: boolean,
  ) => {
    setBusy(true);
    setErrorMessage(null);
    try {
      const saved = await setPreference(accessToken, { category, channel, enabled });
      setPreferences(current => [
        ...current.filter(
          row => !(row.category === saved.category && row.channel === saved.channel),
        ),
        saved,
      ]);
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('notifications.saveFailed'),
      );
    } finally {
      setBusy(false);
    }
  };

  const handleSupport = async (input: {
    category: SupportCategory;
    subject: string;
    body: string;
    orderId?: string;
  }) => {
    setBusy(true);
    setErrorMessage(null);
    try {
      const created = await openSupportRequest(accessToken, input);
      setLastReference(created.reference);
      setRequests(current => [created, ...current]);
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('errors.unexpected'),
      );
    } finally {
      setBusy(false);
    }
  };

  const handleExport = async () => {
    setBusy(true);
    setErrorMessage(null);
    try {
      setExportJob(await requestExport(accessToken));
    } catch (error) {
      setErrorMessage(
        error instanceof ApiError ? error.message : t('errors.unexpected'),
      );
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    setBusy(true);
    setErrorMessage(null);
    try {
      // Clearing the cache first: whatever happens next, this account's data
      // should not be the thing left behind on the handset.
      await clearAccount(userId);
      onAccountDeleted();
    } finally {
      setBusy(false);
    }
  };

  if (loading && receipts.length === 0 && sessions.length === 0) {
    return (
      <View style={styles.container} testID="account-loading">
        <StateMessage
          variant="pending"
          title={t('loading.title')}
          body={t('loading.body')}
        />
      </View>
    );
  }

  if (errorMessage && stage === 'account' && sessions.length === 0 && !offline) {
    return (
      <View style={styles.container} testID="account-error">
        <StateMessage
          variant="error"
          title={t('errors.loadTitle')}
          body={errorMessage}
          actionLabel={t('actions.retry')}
          onAction={() => load().catch(() => undefined)}
        />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {stage === 'devices' ? (
        <DevicesScreen
          sessions={sessions}
          currentSessionId={null}
          busy={busy}
          errorMessage={errorMessage}
          onRevoke={sessionId => handleRevoke(sessionId).catch(() => undefined)}
          onRevokeAll={keepCurrent => handleRevokeAll(keepCurrent).catch(() => undefined)}
          onBack={() => setStage('account')}
        />
      ) : stage === 'receipts' ? (
        <ReceiptsScreen
          receipts={receipts}
          fromCache={offline}
          onBack={() => setStage('account')}
        />
      ) : stage === 'support' ? (
        <SupportScreen
          requests={requests}
          receipts={receipts}
          busy={busy}
          errorMessage={errorMessage}
          lastReference={lastReference}
          onSubmit={input => handleSupport(input).catch(() => undefined)}
          onBack={() => setStage('account')}
        />
      ) : stage === 'notifications' ? (
        <NotificationsScreen
          preferences={preferences}
          busy={busy}
          errorMessage={errorMessage}
          onChange={(category, channel, enabled) =>
            handlePreference(category, channel, enabled).catch(() => undefined)
          }
          onBack={() => setStage('account')}
        />
      ) : stage === 'privacy' ? (
        <PrivacyScreen
          preflight={preflight}
          exportJob={exportJob}
          busy={busy}
          errorMessage={errorMessage}
          onRequestExport={() => handleExport().catch(() => undefined)}
          onDelete={() => handleDelete().catch(() => undefined)}
          onBack={() => setStage('account')}
        />
      ) : (
        <AccountScreen
          displayName={displayName}
          phoneNumber={phoneNumber}
          email={email}
          sessions={sessions}
          receipts={receipts}
          supportRequests={requests}
          observedAt={observedAt}
          offline={offline}
          onOpenDevices={() => setStage('devices')}
          onOpenReceipts={() => setStage('receipts')}
          onOpenSupport={() => setStage('support')}
          onOpenNotifications={() => setStage('notifications')}
          onOpenPrivacy={() => {
            setStage('privacy');
            loadPreflight().catch(() => undefined);
          }}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: color.gray50 },
});
