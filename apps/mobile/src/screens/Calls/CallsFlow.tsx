import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  getEligibility,
  listCalls,
  type AttemptView,
  type EligibilityView,
} from '../../api/callingClient';
import { ApiError } from '../../api/http';
import {
  CallSessionController,
  failureCodeFor,
  type CallSnapshot,
} from '../../services/calling/callSession';
import { resolveCallAdapter } from '../../services/calling/adapterRegistry';
import { requestMicrophone } from '../../services/calling/microphone';
import { CallsScreen, type PayerOption } from './CallsScreen';

/**
 * Owns one customer's calling session for as long as they are signed in.
 *
 * The controller is created per `userId`, and **disposed when that changes**.
 * That is the whole answer to "a delayed SDK callback must not show or control
 * the previous user's call": disposal bumps a generation, and every callback
 * already in flight inside the SDK lands on a generation that no longer
 * matches and is dropped. Doing this in an effect rather than in a sign-out
 * handler matters — a crash-and-remount path never runs a sign-out handler.
 *
 * History is refetched when a call ends rather than appended locally. The cost
 * of a call is derived by the server from provider evidence, and a row this
 * screen invented would be a guess sitting next to facts.
 */

/**
 * The currency a call is priced and billed in.
 *
 * A constant, and a **known limitation**: there is no currency on
 * `/me/session`, and chunk 09 has exactly one supported market today, so there
 * is nothing to derive it from that would not be a guess. An account that can
 * hold more than one currency needs the server to say which one this caller
 * spends — recorded in the handoff rather than papered over here, because a
 * wrong currency would price the call against the wrong balance.
 */
const CALL_CURRENCY = 'NGN';

interface CallsFlowProps {
  accessToken: string;
  userId: string;
  /** Stable per installation. Names the credential a revocation later targets. */
  deviceId: string;
  /** Overrides {@link CALL_CURRENCY}; supplied by tests and future callers. */
  currency?: string;
  /** Organizations this person may bill a call to. Empty for a personal-only account. */
  organizations?: { id: string; name: string }[];
}

export function CallsFlow({
  accessToken,
  userId,
  deviceId,
  currency = CALL_CURRENCY,
  organizations = [],
}: CallsFlowProps): React.JSX.Element {
  const { t } = useTranslation('calling');
  const [destination, setDestination] = useState('');
  const [payerId, setPayerId] = useState<string | null>(null);
  const [eligibility, setEligibility] = useState<EligibilityView | null>(null);
  const [eligibilityLoading, setEligibilityLoading] = useState(false);
  const [eligibilityError, setEligibilityError] = useState<string | null>(null);
  const [history, setHistory] = useState<AttemptView[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<CallSnapshot | null>(null);

  const controllerRef = useRef<CallSessionController | null>(null);

  useEffect(() => {
    const controller = new CallSessionController({
      accessToken,
      userId,
      deviceId,
      adapter: resolveCallAdapter(),
      requestMicrophone,
      onChange: setSnapshot,
    });
    controllerRef.current = controller;
    setSnapshot(controller.snapshot());
    return () => {
      // Disposal, not cleanup. See the component note: this is what stops one
      // account's call reaching the next account's screen.
      controller.dispose();
      controllerRef.current = null;
    };
  }, [accessToken, userId, deviceId]);

  const payers = useMemo<PayerOption[]>(
    () => [
      { id: null, label: t('payer.personal') },
      ...organizations.map(organization => ({
        id: organization.id,
        label: t('payer.work', { organization: organization.name }),
      })),
    ],
    [organizations, t],
  );

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      setHistory(await listCalls({ accessToken, organizationId: payerId, limit: 20 }));
    } catch (error) {
      setHistoryError(failureCodeFor(error));
    } finally {
      setHistoryLoading(false);
    }
  }, [accessToken, payerId]);

  useEffect(() => {
    loadHistory().catch(() => undefined);
  }, [loadHistory]);

  // Price the destination as it is edited. This holds nothing and writes no
  // attempt, so a customer correcting a typo does not watch their balance move.
  useEffect(() => {
    if (!destination.startsWith('+') || destination.length < 7) {
      setEligibility(null);
      setEligibilityError(null);
      return;
    }
    let cancelled = false;
    setEligibilityLoading(true);
    setEligibilityError(null);
    (async () => {
      try {
        const view = await getEligibility({
          accessToken,
          destination,
          currency,
          organizationId: payerId,
        });
        if (!cancelled) setEligibility(view);
      } catch (error) {
        if (!cancelled) {
          setEligibility(null);
          setEligibilityError(
            error instanceof ApiError ? error.code : failureCodeFor(error),
          );
        }
      } finally {
        if (!cancelled) setEligibilityLoading(false);
      }
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [accessToken, destination, currency, payerId]);

  const current = snapshot ?? controllerRef.current?.snapshot();

  const place = useCallback(async () => {
    await controllerRef.current?.place({
      destination,
      currency,
      organizationId: payerId,
    });
  }, [currency, destination, payerId]);

  const hangUp = useCallback(async () => {
    await controllerRef.current?.hangup();
    await loadHistory();
  }, [loadHistory]);

  if (!current) {
    return <></>;
  }

  return (
    <CallsScreen
      destination={destination}
      onDestinationChange={setDestination}
      payers={payers}
      selectedPayerId={payerId}
      onSelectPayer={setPayerId}
      eligibility={eligibility}
      eligibilityLoading={eligibilityLoading}
      eligibilityError={eligibilityError}
      snapshot={current}
      history={history}
      historyLoading={historyLoading}
      historyError={historyError}
      onCall={() => { place().catch(() => undefined); }}
      onHangUp={() => { hangUp().catch(() => undefined); }}
      onToggleMute={() => {
        controllerRef.current?.setMuted(!current.muted).catch(() => undefined);
      }}
      onDigit={digit => {
        controllerRef.current?.sendDigit(digit).catch(() => undefined);
      }}
      onToggleSpeaker={() => {
        controllerRef.current
          ?.setAudioRoute(current.audioRoute === 'speaker' ? 'earpiece' : 'speaker')
          .catch(() => undefined);
      }}
      onDismissFailure={() => {
        loadHistory().catch(() => undefined);
      }}
      onRetry={() => {
        controllerRef.current?.retry().catch(() => undefined);
      }}
    />
  );
}
