import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AppState, Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import {
  confirmInstallation,
  getLine,
  listLines,
  redeemInstallationGrant,
  requestInstallationGrant,
  type InstallationCredential,
  type LineDetail,
  type LineSummary,
} from '../../api/lineClient';
import { ApiError } from '../../api/http';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { downloadEsimProfile } from '../../services/esimDownload';
import {
  protectScreen,
  releaseScreen,
  type ScreenPrivacyResult,
} from '../../services/screenPrivacy';
import { color, radius, space, typography } from '../../theme/tokens';
import { activationGuideFor } from '../EsimActivation/activationGuides';
import { CallingGuideScreen } from './CallingGuideScreen';
import { InstallProfileScreen } from './InstallProfileScreen';
import { MyLineScreen } from './MyLineScreen';

/**
 * My Line, its installation step and its calling guidance (US-38, chunk 20).
 *
 * Three decisions live here rather than in the screens.
 *
 * **The activation code is never held longer than the screen that shows it.**
 * It sits in state while the install screen is mounted and is dropped on the way
 * out — not persisted, not lifted to a parent, not logged. A Telnyx profile is
 * one-time use and cannot be re-downloaded, so a copy that outlives the screen
 * is a copy nobody is watching.
 *
 * **Screen protection is engaged before the code is fetched, not after.** The
 * sequence matters: a `FLAG_SECURE` applied after the profile is on screen has
 * already missed the window it was for. Where the platform offers nothing — iOS
 * has no way to prevent a screenshot — the screen says so rather than implying
 * protection it does not have.
 *
 * **Installing is reported by the device, and only by the device.** Invoking the
 * platform's installer is not a confirmation: the system still asks the customer,
 * they can decline, and `EuiccManager` resolving means the request was accepted,
 * not that a profile is on the phone.
 */

type Stage = 'list' | 'line' | 'install' | 'calling-guide';

interface MyLineFlowProps {
  accessToken: string;
  /** Open this line directly, e.g. from Home's "install now". */
  initialEntitlementId?: string | null;
  onEntitlementOpened?: () => void;
  onBrowsePlans: () => void;
  /** Something changed that Home's service list should re-read. */
  onLineChanged?: () => void;
}

export function MyLineFlow({
  accessToken,
  initialEntitlementId = null,
  onEntitlementOpened,
  onBrowsePlans,
  onLineChanged,
}: MyLineFlowProps): React.JSX.Element {
  const { t } = useTranslation('line');
  const [stage, setStage] = useState<Stage>('list');
  const [lines, setLines] = useState<LineSummary[]>([]);
  const [line, setLine] = useState<LineDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const [credential, setCredential] = useState<InstallationCredential | null>(null);
  const [privacy, setPrivacy] = useState<ScreenPrivacyResult | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [directInstallInvoked, setDirectInstallInvoked] = useState(false);

  /**
   * Guards the reveal against a second tap arriving before `loading` renders.
   * A ref, not state, because both the check and the set have to happen in the
   * same tick — and here a lost race spends a second grant against a profile
   * there is only one of.
   */
  const revealing = useRef(false);
  const installGeneration = useRef(0);
  const installOpen = useRef(false);
  const initialized = useRef(false);
  const readGeneration = useRef(0);

  const describe = useCallback(
    (error: unknown): string =>
      error instanceof ApiError ? error.message : t('errors.unexpected'),
    [t],
  );

  const openLine = useCallback(
    async (entitlementId: string) => {
      const generation = ++readGeneration.current;
      setStage('line');
      setLine(null);
      setLoading(true);
      setErrorMessage(null);
      try {
        const nextLine = await getLine(accessToken, entitlementId);
        if (generation === readGeneration.current) { setLine(nextLine); }
      } catch (error) {
        if (generation === readGeneration.current) { setErrorMessage(describe(error)); }
      } finally {
        if (generation === readGeneration.current) { setLoading(false); }
      }
    },
    [accessToken, describe],
  );

  const loadLines = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const response = await listLines(accessToken);
      setLines(response.lines);
      if (response.lines.length === 1) {
        // One line is the ordinary case, and a list of one is a tap the
        // customer should not have to make.
        await openLine(response.lines[0].entitlement_id);
        return;
      }
      setStage('list');
    } catch (error) {
      setErrorMessage(describe(error));
    } finally {
      setLoading(false);
    }
  }, [accessToken, describe, openLine]);

  useEffect(() => {
    if (initialized.current && !initialEntitlementId) { return; }
    initialized.current = true;
    if (initialEntitlementId) {
      openLine(initialEntitlementId);
      onEntitlementOpened?.();
      return;
    }
    loadLines();
    // Cold-start decision, deliberately once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialEntitlementId]);

  // --- installation --------------------------------------------------------

  const enterInstall = useCallback(async () => {
    const generation = ++installGeneration.current;
    installOpen.current = true;
    revealing.current = false;
    setLoading(false);
    setPrivacy(null);
    setCredential(null);
    setInstallError(null);
    setDirectInstallInvoked(false);
    setStage('install');
    // Before anything is fetched. The order is the protection.
    const result = await protectScreen();
    if (generation === installGeneration.current) {
      setPrivacy(result);
    } else if (!installOpen.current) {
      await releaseScreen();
    }
  }, []);

  const leaveInstall = useCallback(async () => {
    installGeneration.current += 1;
    installOpen.current = false;
    revealing.current = false;
    setLoading(false);
    setBusy(false);
    setCredential(null);
    setInstallError(null);
    setPrivacy(null);
    setStage('line');
    // Clearing the flag matters: it is set on the Activity window, so leaving it
    // behind makes every later screen unscreenshottable — including the ones
    // support asks customers to send.
    await releaseScreen();
  }, []);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      if (state !== 'active' && installOpen.current) {
        installGeneration.current += 1;
        revealing.current = false;
        setCredential(null);
        setInstallError(null);
        setLoading(false);
      }
    });
    return () => {
      subscription.remove();
      installGeneration.current += 1;
      readGeneration.current += 1;
      installOpen.current = false;
      releaseScreen().catch(() => undefined);
    };
  }, []);

  const reveal = useCallback(async () => {
    if (!line || revealing.current || !installOpen.current || privacy === null) {
      return;
    }
    const generation = installGeneration.current;
    revealing.current = true;
    setLoading(true);
    setInstallError(null);
    try {
      const grant = await requestInstallationGrant(
        accessToken,
        line.entitlement_id,
      );
      if (generation !== installGeneration.current) { return; }
      const material = await redeemInstallationGrant(
          accessToken,
          line.entitlement_id,
          grant.grant_token,
      );
      if (generation === installGeneration.current) { setCredential(material); }
    } catch (error) {
      if (generation === installGeneration.current) { setInstallError(describe(error)); }
    } finally {
      if (generation === installGeneration.current) {
        revealing.current = false;
        setLoading(false);
      }
    }
  }, [accessToken, describe, line, privacy]);

  const directInstall = useCallback(async () => {
    if (!credential) {
      return;
    }
    setBusy(true);
    setInstallError(null);
    try {
      const outcome = await downloadEsimProfile(credential.lpa);
      // `invoked` means the system accepted the request and is asking the
      // customer. It is not an installation, and the screen does not say it is.
      setDirectInstallInvoked(outcome === 'invoked');
    } catch {
      // Native/provider errors may echo the activation code.
      setInstallError(t('errors.unexpected'));
    } finally {
      setBusy(false);
    }
  }, [credential, t]);

  const reportInstallation = useCallback(
    async (installed: boolean) => {
      if (!line) {
        return;
      }
      setBusy(true);
      setInstallError(null);
      try {
        const refreshed = await confirmInstallation(
          accessToken,
          line.entitlement_id,
          installed,
        );
        setLine(refreshed);
        onLineChanged?.();
        await leaveInstall();
      } catch (error) {
        setInstallError(describe(error));
      } finally {
        setBusy(false);
      }
    },
    [accessToken, describe, leaveInstall, line, onLineChanged],
  );

  // --- render --------------------------------------------------------------

  if (stage === 'install' && line) {
    return (
      <InstallProfileScreen
        credential={credential}
        guide={activationGuideFor(
          Platform.OS === 'ios' ? 'ios' : 'android',
          DeviceInfo.getModel(),
        )}
        privacy={privacy}
        loading={loading}
        busy={busy}
        errorMessage={installError}
        directInstallInvoked={directInstallInvoked}
        onReveal={reveal}
        onDirectInstall={directInstall}
        onConfirmInstalled={() => reportInstallation(true)}
        onReportFailed={() => reportInstallation(false)}
        onBack={leaveInstall}
      />
    );
  }

  if (stage === 'calling-guide' && line) {
    return <CallingGuideScreen line={line} onBack={() => setStage('line')} />;
  }

  if (stage === 'line') {
    if (line === null) {
      return (
        <ScrollView contentContainerStyle={styles.screen} testID="my-line-loading">
          <StateMessage
            variant={errorMessage ? 'error' : 'pending'}
            title={errorMessage ? t('errors.loadTitle') : t('loading.title')}
            body={errorMessage ?? t('loading.body')}
            actionLabel={t('actions.refresh')}
            onAction={loadLines}
            busy={loading}
            testID="my-line-loading-state"
          />
        </ScrollView>
      );
    }
    return (
      <MyLineScreen
        line={line}
        loading={loading}
        errorMessage={errorMessage}
        onRefresh={() => openLine(line.entitlement_id)}
        onInstall={enterInstall}
        onOpenCallingGuide={() => setStage('calling-guide')}
        onBrowsePlans={onBrowsePlans}
      />
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="my-line-list">
      {errorMessage ? (
        <StateMessage
          variant="error"
          title={t('errors.loadTitle')}
          body={errorMessage}
          actionLabel={t('actions.retry')}
          onAction={loadLines}
          busy={loading}
          testID="my-line-list-error"
        />
      ) : lines.length === 0 && !loading ? (
        <StateMessage
          variant="empty"
          title={t('empty.title')}
          body={t('empty.body')}
          actionLabel={t('empty.action')}
          onAction={onBrowsePlans}
          testID="my-line-empty"
        />
      ) : (
        <>
          <Text style={styles.title}>{t('list.title')}</Text>
          {lines.map(summary => (
            <View
              key={summary.entitlement_id}
              style={styles.card}
              testID={`my-line-card-${summary.entitlement_id}`}
            >
              <Text style={styles.cardTitle}>{summary.product_name}</Text>
              <Text style={styles.cardMeta}>
                {summary.e164 ??
                  (summary.number_status === 'pending'
                    ? t('number.pending')
                    : t('number.notIncluded'))}
              </Text>
              <SecondaryButton
                label={t('list.open')}
                onPress={() => openLine(summary.entitlement_id)}
                testID={`my-line-open-${summary.entitlement_id}`}
              />
            </View>
          ))}
        </>
      )}
    </ScrollView>
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
  card: {
    padding: space.space4,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: color.gray200,
    backgroundColor: color.white,
    gap: space.space2,
  },
  cardTitle: {
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
