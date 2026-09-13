import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useTranslation } from 'react-i18next';

import type { AttemptView, EligibilityView } from '../../api/callingClient';
import type { CallSnapshot } from '../../services/calling/callSession';
import { CallInProgress } from './CallInProgress';
import { Keypad } from './Keypad';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';

/**
 * The Calls tab (US-47, AC-47.1).
 *
 * What it is careful about:
 *
 * **It names the mode.** Every call this screen can place is an *internet*
 * call, and it says so. A carrier call is placed by the phone's own dialler and
 * DamDam cannot start one — the two bill differently and fail differently, and
 * somebody who thinks they are making one while making the other gets a
 * surprise on a bill. Nothing here touches SIM selection, and changing the
 * payer does not and cannot change which SIM a carrier call would use.
 *
 * **The payer is a decision, not a default.** Choosing work says, in words,
 * that the organization can see the call happened, how long it lasted and what
 * it cost. That belongs before the call, not in a policy document.
 *
 * **It needs no eSIM.** There is no installation check anywhere on this path.
 * An internet-only customer reaches a working call button.
 *
 * **The rate preview commits nothing.** `GET /calls/eligibility` holds no money
 * and writes no attempt, so a customer editing a number does not watch their
 * balance flicker.
 */

export interface PayerOption {
  id: string | null;
  label: string;
}

interface CallsScreenProps {
  destination: string;
  onDestinationChange: (value: string) => void;
  payers: PayerOption[];
  selectedPayerId: string | null;
  onSelectPayer: (id: string | null) => void;
  eligibility: EligibilityView | null;
  eligibilityLoading: boolean;
  eligibilityError: string | null;
  snapshot: CallSnapshot;
  history: AttemptView[];
  historyLoading: boolean;
  historyError: string | null;
  onCall: () => void;
  onHangUp: () => void;
  onToggleMute: () => void;
  onDigit: (digit: string) => void;
  onToggleSpeaker: () => void;
  onDismissFailure: () => void;
  onRetry: () => void;
}

const LIVE = new Set(['preparing', 'connecting', 'ringing', 'answered']);

function minutesFor(seconds: number): number {
  return Math.max(1, Math.floor(seconds / 60));
}

export function CallsScreen(props: CallsScreenProps): React.JSX.Element {
  const { t } = useTranslation('calling');
  const {
    destination,
    onDestinationChange,
    payers,
    selectedPayerId,
    onSelectPayer,
    eligibility,
    eligibilityLoading,
    eligibilityError,
    snapshot,
    history,
    historyLoading,
    historyError,
    onCall,
  } = props;

  const live = LIVE.has(snapshot.phase);
  const callable =
    !live &&
    destination.startsWith('+') &&
    destination.length > 6 &&
    eligibility !== null &&
    eligibility.route_enabled &&
    eligibility.fundable;

  if (live) {
    return (
      <ScrollView contentContainerStyle={styles.container} testID="calls-screen">
        <CallInProgress
          snapshot={snapshot}
          onHangUp={props.onHangUp}
          onToggleMute={props.onToggleMute}
          onDigit={props.onDigit}
          onToggleSpeaker={props.onToggleSpeaker}
        />
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.container} testID="calls-screen">
      <Text style={styles.title}>{t('title')}</Text>
      <Text style={styles.subtitle}>{t('subtitle')}</Text>

      {/* Mode is stated, never inferred from which screen you are on. */}
      <View style={styles.modeCard} testID="calls-mode">
        <Text style={styles.modeLabel}>{t('mode.internet')}</Text>
        <Text style={styles.caption}>{t('mode.internetExplainer')}</Text>
        <Text style={styles.caption} testID="calls-carrier-note">
          {t('mode.carrierExplainer')}
        </Text>
      </View>

      <Text style={styles.label}>{t('destination.label')}</Text>
      <Text style={styles.destination} testID="calls-destination">
        {destination || t('destination.hint')}
      </Text>
      <Keypad
        onPress={digit =>
          onDestinationChange(destination === '' ? `+${digit}` : `${destination}${digit}`)
        }
        testIDPrefix="dial"
      />
      <Pressable
        testID="calls-backspace"
        accessibilityRole="button"
        accessibilityLabel={t('destination.clear')}
        onPress={() => onDestinationChange(destination.slice(0, -1))}
        style={styles.secondary}
      >
        <Text style={styles.secondaryLabel}>{t('destination.clear')}</Text>
      </Pressable>

      {payers.length > 1 ? (
        <View style={styles.block} testID="calls-payer">
          <Text style={styles.label}>{t('payer.label')}</Text>
          {payers.map(payer => (
            <Pressable
              key={payer.id ?? 'personal'}
              testID={`calls-payer-${payer.id ?? 'personal'}`}
              accessibilityRole="radio"
              accessibilityState={{ selected: payer.id === selectedPayerId }}
              onPress={() => onSelectPayer(payer.id)}
              style={[
                styles.payerOption,
                payer.id === selectedPayerId ? styles.payerSelected : null,
              ]}
            >
              <Text style={styles.payerLabel}>{payer.label}</Text>
            </Pressable>
          ))}
          <Text style={styles.caption} testID="calls-payer-disclosure">
            {selectedPayerId
              ? t('payer.workDisclosure')
              : t('payer.personalDisclosure')}
          </Text>
        </View>
      ) : (
        <Text style={styles.caption}>{t('payer.personalDisclosure')}</Text>
      )}

      <View style={styles.block} testID="calls-preview">
        <Text style={styles.label}>{t('preview.heading')}</Text>
        {eligibilityLoading ? (
          <Text style={styles.caption}>{t('preview.checking')}</Text>
        ) : eligibilityError ? (
          <Text style={styles.error} testID="calls-preview-error">
            {t(`failure.${eligibilityError}`, { defaultValue: t('preview.unavailable') })}
          </Text>
        ) : eligibility ? (
          <>
            <Text style={styles.previewLine} testID="calls-rate">
              {t('preview.rate', {
                amount: eligibility.rate_per_minute_amount,
                currency: eligibility.currency,
              })}
            </Text>
            <Text style={styles.previewLine}>
              {t('preview.maximum', {
                amount: eligibility.max_charge_amount,
                currency: eligibility.currency,
                minutes: minutesFor(eligibility.max_seconds),
              })}
            </Text>
            <Text style={styles.caption}>
              {t('preview.available', {
                amount: eligibility.available_amount,
                currency: eligibility.currency,
              })}
            </Text>
            {!eligibility.route_enabled ? (
              <Text style={styles.error} testID="calls-route-disabled">
                {t('preview.routeDisabled')}
              </Text>
            ) : null}
            {eligibility.route_enabled && !eligibility.fundable ? (
              <Text style={styles.error} testID="calls-not-fundable">
                {t('preview.notFundable')}
              </Text>
            ) : null}
          </>
        ) : (
          <Text style={styles.caption}>{t('destination.hint')}</Text>
        )}
      </View>

      <Pressable
        testID="calls-place"
        accessibilityRole="button"
        accessibilityState={{ disabled: !callable }}
        disabled={!callable}
        onPress={onCall}
        style={[styles.primary, !callable ? styles.primaryDisabled : null]}
      >
        <Text style={styles.primaryLabel}>{t('action.call')}</Text>
      </Pressable>

      {snapshot.phase === 'failed' && snapshot.failureCode ? (
        <View style={styles.failure} testID="calls-failure">
          <Text style={styles.error}>
            {t(`failure.${snapshot.failureCode}`, {
              defaultValue: t('failure.generic'),
            })}
          </Text>
          <View style={styles.controlsRow}>
            <Pressable
              testID="calls-failure-retry"
              accessibilityRole="button"
              onPress={props.onRetry}
              style={styles.secondary}
            >
              <Text style={styles.secondaryLabel}>{t('action.retry')}</Text>
            </Pressable>
            <Pressable
              testID="calls-failure-dismiss"
              accessibilityRole="button"
              onPress={props.onDismissFailure}
              style={styles.secondary}
            >
              <Text style={styles.secondaryLabel}>{t('action.dismiss')}</Text>
            </Pressable>
          </View>
        </View>
      ) : null}

      <View style={styles.block} testID="calls-history">
        <Text style={styles.label}>{t('history.heading')}</Text>
        {historyLoading ? (
          <Text style={styles.caption}>{t('history.loading')}</Text>
        ) : historyError ? (
          <Text style={styles.error}>{t('history.error')}</Text>
        ) : history.length === 0 ? (
          <Text style={styles.caption}>{t('history.empty')}</Text>
        ) : (
          history.map(attempt => (
            <View
              key={attempt.attempt_id}
              style={styles.historyRow}
              testID={`calls-history-${attempt.attempt_id}`}
            >
              <Text style={styles.historyDestination}>{attempt.destination_e164}</Text>
              <Text style={styles.caption}>
                {t(`history.scope.${attempt.organization_id ? 'work' : 'personal'}`)}
              </Text>
              <Text style={styles.caption} testID={`calls-cost-${attempt.attempt_id}`}>
                {/* A missing charge is "not settled yet", never zero. V03 may
                    still be waiting on the supplier's own record. */}
                {attempt.charge === null
                  ? attempt.answered_at === null
                    ? t('history.unanswered')
                    : t('history.costPending')
                  : attempt.charge.is_final
                    ? t('history.cost', {
                        amount: attempt.charge.amount,
                        currency: attempt.charge.currency,
                      })
                    : t('history.costProvisional', {
                        amount: attempt.charge.amount,
                        currency: attempt.charge.currency,
                      })}
              </Text>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: space.space4, gap: space.space3, paddingBottom: space.space12 },
  title: { ...typography.heading1, color: color.gray900 },
  subtitle: { ...typography.body, color: color.gray700 },
  modeCard: {
    gap: space.space1,
    padding: space.space3,
    borderRadius: radius.card,
    backgroundColor: color.info100,
  },
  modeLabel: { ...typography.heading3, color: color.info700 },
  label: { ...typography.caption, color: color.gray600 },
  destination: { ...typography.display, color: color.gray900 },
  block: { gap: space.space2 },
  payerOption: {
    minHeight: minTouchTarget,
    justifyContent: 'center',
    paddingHorizontal: space.space3,
    borderRadius: radius.button,
    backgroundColor: color.gray100,
  },
  payerSelected: { backgroundColor: color.primary100 },
  payerLabel: { ...typography.body, color: color.gray900 },
  previewLine: { ...typography.body, color: color.gray900 },
  caption: { ...typography.caption, color: color.gray600 },
  error: { ...typography.caption, color: color.error700 },
  failure: { gap: space.space2 },
  controlsRow: { flexDirection: 'row', gap: space.space2 },
  primary: {
    minHeight: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.button,
    backgroundColor: color.success700,
  },
  primaryDisabled: { opacity: 0.4 },
  primaryLabel: { ...typography.body, color: color.white, fontWeight: '600' },
  secondary: {
    minHeight: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.space3,
    borderRadius: radius.button,
    backgroundColor: color.gray100,
  },
  secondaryLabel: { ...typography.caption, color: color.gray900 },
  historyRow: { gap: space.space1, paddingVertical: space.space2 },
  historyDestination: { ...typography.body, color: color.gray900 },
});
