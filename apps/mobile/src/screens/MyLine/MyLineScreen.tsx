import React from 'react';
import { useTranslation } from 'react-i18next';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { LineDetail } from '../../api/lineClient';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { StateMessage } from '../../components/StateMessage/StateMessage';
import { StatusPill } from '../../components/StatusPill/StatusPill';
import { UsageMeter } from '../../components/UsageMeter/UsageMeter';
import { color, radius, space, typography } from '../../theme/tokens';
import {
  ageUnit,
  dataAllowance,
  minutesFromSeconds,
  money,
  observedAgeMinutes,
  remainingFraction,
} from '../../utils/format';

interface MyLineScreenProps {
  line: LineDetail;
  loading: boolean;
  errorMessage: string | null;
  onRefresh: () => void;
  onInstall: () => void;
  onOpenCallingGuide: () => void;
  onBrowsePlans: () => void;
}

/**
 * My Line (US-38, AC-38.1–AC-38.4).
 *
 * The screen answers four questions in the order a customer asks them: *what is
 * my number*, *does it work*, *how much is left*, and *what do I do next*. What
 * it never does is merge them.
 *
 * Four pills rather than one status, because the states genuinely disagree: a
 * profile can sit installed on a phone that never attaches, and a line can be
 * suspended with the profile still on the device. A single "status" would have
 * to lie about at least one of those, and it would do it on the screen a support
 * agent reads out loud.
 *
 * The usage meter carries its own age and refuses to draw a balance nobody has
 * measured — `freshness: "unknown"` means the grant is all we have, and drawing
 * it as a reading is what AC-36.4 forbids.
 */
export function MyLineScreen({
  line,
  loading,
  errorMessage,
  onRefresh,
  onInstall,
  onOpenCallingGuide,
  onBrowsePlans,
}: MyLineScreenProps): React.JSX.Element {
  const { t } = useTranslation('line');
  const next = nextStep(line);

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="my-line">
      <Text style={styles.title}>{line.product_name}</Text>

      {/* --- the number ---------------------------------------------------- */}
      <View style={styles.card} testID="my-line-number">
        <Text style={styles.cardLabel}>{t('number.label')}</Text>
        {line.number_status === 'assigned' && line.assigned_number ? (
          <Text style={styles.number} testID="my-line-number-value">
            {line.assigned_number.e164}
          </Text>
        ) : (
          <Text style={styles.numberAbsent} testID="my-line-number-absent">
            {line.number_status === 'pending'
              ? t('number.pending')
              : t('number.notIncluded')}
          </Text>
        )}
      </View>

      {/* --- what to do next ----------------------------------------------- */}
      {next === 'install' ? (
        <StateMessage
          variant="pending"
          title={t('next.installTitle')}
          body={t('next.installBody')}
          actionLabel={t('next.installAction')}
          onAction={onInstall}
          testID="my-line-next-install"
        />
      ) : next === 'awaiting-profile' ? (
        <StateMessage
          variant="pending"
          title={t('next.awaitingProfileTitle')}
          body={t('next.awaitingProfileBody')}
          footnote={t('next.awaitingProfileFootnote')}
          actionLabel={t('actions.refresh')}
          onAction={onRefresh}
          busy={loading}
          testID="my-line-next-awaiting"
        />
      ) : next === 'awaiting-activation' ? (
        /*
          Installed, not active. The honest sentence, because the profile being
          on the phone is not the carrier agreeing to carry its traffic — and
          telling somebody their line is ready here is telling them their phone
          works when it does not.
        */
        <StateMessage
          variant="pending"
          title={t('next.awaitingActivationTitle')}
          body={t('next.awaitingActivationBody')}
          actionLabel={t('actions.refresh')}
          onAction={onRefresh}
          busy={loading}
          testID="my-line-next-activation"
        />
      ) : next === 'suspended' ? (
        <StateMessage
          variant="blocked"
          title={t('next.suspendedTitle')}
          body={t('next.suspendedBody')}
          footnote={line.restriction?.detail ?? undefined}
          testID="my-line-next-suspended"
        />
      ) : next === 'expired' ? (
        <StateMessage
          variant="blocked"
          title={t('next.expiredTitle')}
          body={t('next.expiredBody')}
          actionLabel={t('next.expiredAction')}
          onAction={onBrowsePlans}
          testID="my-line-next-expired"
        />
      ) : (
        <StateMessage
          variant="empty"
          title={t('next.readyTitle')}
          body={t('next.readyBody')}
          testID="my-line-next-ready"
        />
      )}

      {errorMessage ? (
        <Banner tone="error" testID="my-line-error" message={errorMessage} />
      ) : null}

      {/* --- the four states ------------------------------------------------ */}
      {line.installation || line.line ? (
        <View style={styles.card} testID="my-line-states">
          <Text style={styles.cardLabel}>{t('states.label')}</Text>
          <View style={styles.pills}>
            {line.installation ? (
              <StatusPill
                family={t('states.installation')}
                tone={
                  line.installation.state === 'installed' ? 'positive' : 'caution'
                }
                label={t(`states.installationValue.${line.installation.state}`)}
                testID="my-line-pill-installation"
              />
            ) : null}
            {line.line ? (
              <>
                <StatusPill
                  family={t('states.activation')}
                  tone={
                    line.line.activation_state === 'active'
                      ? 'positive'
                      : line.line.activation_state === 'terminated'
                        ? 'negative'
                        : 'caution'
                  }
                  label={t(`states.activationValue.${line.line.activation_state}`)}
                  testID="my-line-pill-activation"
                />
                <StatusPill
                  family={t('states.network')}
                  // `unknown` is neutral, not negative. Nobody has told us, and
                  // rendering that as a failure invents a fact in the other
                  // direction.
                  tone={
                    line.line.network_state === 'attached'
                      ? 'positive'
                      : line.line.network_state === 'detached'
                        ? 'caution'
                        : 'neutral'
                  }
                  label={t(`states.networkValue.${line.line.network_state}`)}
                  testID="my-line-pill-network"
                />
                <StatusPill
                  family={t('states.voice')}
                  tone={line.line.voice_enabled ? 'positive' : 'neutral'}
                  label={
                    line.line.voice_enabled
                      ? t('states.voiceValue.enabled')
                      : t('states.voiceValue.notEnabled')
                  }
                  testID="my-line-pill-voice"
                />
              </>
            ) : null}
          </View>
          {line.line?.provider_status ? (
            <Text style={styles.footnote} testID="my-line-provider-status">
              {t('states.providerStatus', { status: line.line.provider_status })}
            </Text>
          ) : null}
        </View>
      ) : null}

      {/* --- usage ---------------------------------------------------------- */}
      <View style={styles.card} testID="my-line-usage">
        <Text style={styles.cardLabel}>{t('usage.label')}</Text>
        <UsageMeter
          label={t('usage.data')}
          remaining={dataAllowance(line.usage.data_bytes_remaining) ?? t('usage.none')}
          total={dataAllowance(line.usage.data_bytes_total) ?? t('usage.none')}
          fraction={remainingFraction(
            line.usage.data_bytes_remaining,
            line.usage.data_bytes_total,
          )}
          updatedLabel={updatedLabel(line, t)}
          stale={line.usage.freshness === 'stale'}
          explanation={freshnessExplanation(line, t)}
          testID="my-line-usage-data"
        />
        {line.usage.voice_seconds_total > 0 ? (
          <UsageMeter
            label={t('usage.calls')}
            remaining={t('usage.minutes', {
              minutes: minutesFromSeconds(line.usage.voice_seconds_remaining),
            })}
            total={t('usage.minutes', {
              minutes: minutesFromSeconds(line.usage.voice_seconds_total),
            })}
            fraction={remainingFraction(
              line.usage.voice_seconds_remaining,
              line.usage.voice_seconds_total,
            )}
            updatedLabel={updatedLabel(line, t)}
            stale={line.usage.freshness === 'stale'}
            testID="my-line-usage-voice"
          />
        ) : null}
        {line.usage.has_provisional ? (
          <Banner
            tone="info"
            testID="my-line-provisional"
            message={t('usage.provisional')}
          />
        ) : null}
        {line.top_ups.pending_count > 0 ? (
          /*
            Paid for and not yet usable. Said out loud because the alternative
            is a customer who has paid seeing no change and buying again.
          */
          <Banner
            tone="info"
            testID="my-line-pending-top-up"
            message={t('usage.pendingTopUp', { count: line.top_ups.pending_count })}
          />
        ) : null}
      </View>

      {/* --- restriction ----------------------------------------------------- */}
      {line.restriction && line.restriction.enforcement === 'none' ? (
        <Banner
          tone="info"
          testID="my-line-no-enforcement"
          message={t('restriction.noEnforcement')}
        />
      ) : null}
      {line.restriction?.confirmed_limit_bytes ? (
        <Text style={styles.footnote} testID="my-line-confirmed-limit">
          {t('restriction.confirmedLimit', {
            amount: dataAllowance(line.restriction.confirmed_limit_bytes) ?? '',
          })}
        </Text>
      ) : null}

      {/* --- calls ------------------------------------------------------------ */}
      <View style={styles.card} testID="my-line-calling">
        <Text style={styles.cardLabel}>{t('calling.label')}</Text>
        {line.calling.native_available ? (
          <Text style={styles.body} testID="my-line-native-available">
            {t('calling.nativeAvailable')}
          </Text>
        ) : (
          <Text style={styles.body} testID="my-line-native-unavailable">
            {t(
              `calling.nativeUnavailable.${line.calling.native_unavailable_reason ?? 'unknown'}`,
              { defaultValue: t('calling.nativeUnavailable.unknown') },
            )}
          </Text>
        )}
        {/*
          The internet dialer is V04's and is not accepted, so there is no button
          here — only a sentence saying calls go through the phone's own dialer.
          An entry point to something that does not exist is worse than its
          absence.
        */}
        {!line.calling.internet_dialer_enabled ? (
          <Text style={styles.footnote} testID="my-line-internet-dialer">
            {t('calling.internetDialerUnavailable')}
          </Text>
        ) : null}
        {line.calling.requires_line_selection ? (
          <SecondaryButton
            label={t('calling.guideAction')}
            onPress={onOpenCallingGuide}
            testID="my-line-calling-guide"
          />
        ) : null}
      </View>

      {/* --- tariff ----------------------------------------------------------- */}
      {line.tariff ? (
        <View style={styles.card} testID="my-line-tariff">
          <Text style={styles.cardLabel}>{t('tariff.label')}</Text>
          {line.tariff.destinations.map(destination => (
            <Text
              key={`${destination.origin_country}-${destination.country}-${destination.destination_kind}`}
              style={styles.body}
              testID={`my-line-rate-${destination.country}`}
            >
              {t('tariff.rate', {
                country: destination.country,
                origin: destination.origin_country ?? t('tariff.anyOrigin'),
                kind: t(`tariff.kind.${destination.destination_kind}`, {
                  defaultValue: destination.destination_kind,
                }),
                amount: money(
                  destination.per_minute_amount,
                  line.tariff?.currency ?? '',
                ),
                increment: destination.increment_seconds,
                minimum: destination.minimum_seconds,
                setup: money(destination.setup_amount, line.tariff.currency),
              })}
            </Text>
          ))}
          <Text style={styles.footnote}>
            {t('tariff.version', { version: line.tariff.version })}
          </Text>
        </View>
      ) : (
        <Banner
          tone="neutral"
          testID="my-line-no-tariff"
          message={t('tariff.none')}
        />
      )}

      <PrimaryButton
        label={t('actions.refresh')}
        onPress={onRefresh}
        loading={loading}
        testID="my-line-refresh"
      />
    </ScrollView>
  );
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

function updatedLabel(line: LineDetail, t: Translate): string | null {
  const minutes = observedAgeMinutes(line.usage.observed_at);
  if (minutes === null) {
    // `UsageMeter` renders `null` as "never reported" rather than as an age,
    // which is a different statement from "zero used".
    return null;
  }
  const { unit, value } = ageUnit(minutes);
  return t(`usage.age.${unit}`, { value });
}

function freshnessExplanation(line: LineDetail, t: Translate): string | undefined {
  if (line.usage.freshness === 'unknown') {
    return t('usage.neverReported');
  }
  if (line.usage.freshness === 'stale') {
    return t('usage.stale');
  }
  return undefined;
}

type NextStep =
  | 'install'
  | 'awaiting-profile'
  | 'awaiting-activation'
  | 'suspended'
  | 'expired'
  | 'ready';

/**
 * The single next action, chosen by what the customer can actually do.
 *
 * Ordered by actionability rather than severity. Expiry and suspension come
 * first because nothing else is worth doing while either holds; after that,
 * installing is the only step the customer performs themselves, and everything
 * remaining is a wait with an honest name.
 */
export function nextStep(line: LineDetail): NextStep {
  if (line.usage.expired) {
    return 'expired';
  }
  if (line.restriction?.suspended) {
    return 'suspended';
  }
  if (line.delivery === 'internet') {
    return 'ready';
  }
  if (!line.installation) { return 'awaiting-profile'; }
  if (line.installation.state !== 'installed') {
    // A profile that has not been issued yet is a wait, not a task. Offering
    // "install" against a credential that does not exist sends the customer to
    // a screen that can only apologize.
    return line.installation.credential_available ? 'install' : 'awaiting-profile';
  }
  if (line.line?.activation_state !== 'active') {
    return 'awaiting-activation';
  }
  return 'ready';
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
    gap: space.space3,
  },
  cardLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  number: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  numberAbsent: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  pills: { flexDirection: 'row', flexWrap: 'wrap', gap: space.space2 },
  body: {
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
