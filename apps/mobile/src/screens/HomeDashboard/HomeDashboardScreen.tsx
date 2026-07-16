import {
  ChatCircle,
  CheckCircle,
  Clock,
  Phone,
  Siren,
  WarningCircle,
} from 'phosphor-react-native';
import React, { useState } from 'react';
import {Linking, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {SUPPORT_WHATSAPP_NUMBER} from '../../config/env';
import { shouldShowDateActivationBanner } from '../../services/arrivalPrompts';
import { color, radius, space, typography } from '../../theme/tokens';
import { EsimActivationBanner } from './EsimActivationBanner';

interface HomeDashboardScreenProps {
  departureDate: string | null;
  esimStatus: 'issued' | 'downloaded' | 'activated' | 'not_issued';
  remainingDataGb: number | null;
  dataTotalGb: number | null;
  pstnMinutesRemaining: number | null;
  pstnMinutesTotal: number | null;
  onActivateEsim: () => void;
  now?: Date;
  onOpenCall?: () => void;
  onCheckIn?: () => Promise<'sent' | 'queued'>;
  lastCheckInAt?: string | null;
  queuedCheckIns?: number;
  queuedSOSAlerts?: number;
  onOpenSOS?: () => void;
}

export function HomeDashboardScreen({
  departureDate,
  esimStatus,
  remainingDataGb,
  dataTotalGb,
  pstnMinutesRemaining,
  pstnMinutesTotal,
  onActivateEsim,
  now = new Date(),
  onOpenCall,
  onCheckIn,
  lastCheckInAt = null,
  queuedCheckIns = 0,
  queuedSOSAlerts = 0,
  onOpenSOS,
}: HomeDashboardScreenProps): React.JSX.Element {
  const [dismissedThisSession, setDismissedThisSession] = useState(false);
  const [checkInFeedback, setCheckInFeedback] = useState<string>();
  const [checkingIn, setCheckingIn] = useState(false);
  const lastCheckInTime = lastCheckInAt ? new Date(lastCheckInAt).getTime() : 0;
  const rateLimited =
    lastCheckInTime > 0 && now.getTime() - lastCheckInTime < 15 * 60 * 1000;
  const checkInForeground = rateLimited ? color.gray500 : color.white;
  const showBanner =
    !dismissedThisSession &&
    shouldShowDateActivationBanner(departureDate, esimStatus, now);
  const queuedEvents = queuedCheckIns + queuedSOSAlerts;
  const dataPercent = percentage(remainingDataGb, dataTotalGb);
  const minutesPercent = percentage(pstnMinutesRemaining, pstnMinutesTotal);
  const balanceTone =
    remainingDataGb === null || pstnMinutesRemaining === null
      ? 'healthy'
      : getHomeBalanceTone(dataPercent, pstnMinutesRemaining);

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Home</Text>
      <View style={styles.checkInControl}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="I'm okay"
          disabled={!onCheckIn || checkingIn || rateLimited}
          onPress={() => {
            if (!onCheckIn) return;
            setCheckingIn(true);
            onCheckIn()
              .then(result =>
                setCheckInFeedback(
                  result === 'sent'
                    ? 'Check-in sent'
                    : 'Check-in queued, will send when connected',
                ),
              )
              .catch(() => setCheckInFeedback('Check-in unavailable — try again'))
              .finally(() => setCheckingIn(false));
          }}
          style={({pressed}) => [
            styles.checkInButton,
            (!onCheckIn || checkingIn || rateLimited) && styles.disabledButton,
            pressed && styles.pressedButton,
          ]}>
          <CheckCircle color={checkInForeground} size={24} weight="bold" />
          <Text
            style={[
              styles.checkInButtonLabel,
              rateLimited && styles.disabledButtonLabel,
            ]}>
            {checkingIn ? 'Saving check-in…' : "I'm okay"}
          </Text>
        </Pressable>
        {rateLimited ? (
          <Text style={styles.rateLimitHint}>Check-in available every 15 minutes</Text>
        ) : null}
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="SOS / Emergency"
        accessibilityHint="Opens the three-second emergency hold control"
        onPress={onOpenSOS}
        disabled={!onOpenSOS}
        style={({pressed}) => [styles.sosButton, pressed && styles.pressedButton]}>
        <Siren color={color.white} size={28} weight="fill" />
        <Text style={styles.sosButtonLabel}>SOS / Emergency</Text>
      </Pressable>
      {checkInFeedback ? (
        <View
          accessibilityLiveRegion="polite"
          style={
            checkInFeedback === 'Check-in sent'
              ? styles.successBanner
              : checkInFeedback.includes('queued')
                ? styles.queueBanner
                : styles.errorBanner
          }>
          {checkInFeedback === 'Check-in sent' ? (
            <CheckCircle color={color.success500} size={24} weight="bold" />
          ) : checkInFeedback.includes('queued') ? (
            <Clock color={color.gray700} size={24} weight="bold" />
          ) : (
            <WarningCircle color={color.error700} size={24} weight="bold" />
          )}
          <Text
            style={[
              styles.bannerText,
              checkInFeedback.includes('queued') && styles.queueBannerText,
            ]}>
            {checkInFeedback}
          </Text>
        </View>
      ) : null}
      {queuedEvents > 0 ? (
        <View style={styles.queueBanner} testID="queued-events-indicator">
          <Clock color={color.gray700} size={24} weight="bold" />
          <View style={styles.queueCopy}>
            <Text style={[styles.bannerText, styles.queueBannerText]}>
              {queuedEvents} {queuedEvents === 1 ? 'event' : 'events'} waiting to send
            </Text>
            <Text style={styles.queueDetail}>
              {queueBreakdown(queuedCheckIns, queuedSOSAlerts)}
            </Text>
          </View>
        </View>
      ) : null}
      <Text style={styles.lastCheckIn}>
        Last check-in:{' '}
        {lastCheckInAt
          ? new Date(lastCheckInAt).toLocaleString([], {
              day: 'numeric',
              month: 'short',
              hour: '2-digit',
              minute: '2-digit',
            })
          : 'Not yet'}
      </Text>
      {showBanner ? (
        <EsimActivationBanner
          onActivate={onActivateEsim}
          onDismiss={() => setDismissedThisSession(true)}
        />
      ) : null}
      {remainingDataGb !== null && balanceTone === 'warning' ? (
        <View style={styles.warningBanner} testID="balance-warning-banner">
          <WarningCircle color={color.warning500} size={24} weight="bold" />
          <Text style={styles.bannerText}>
            Balance running low. Message support if you need more data or minutes.
          </Text>
        </View>
      ) : null}
      {remainingDataGb !== null && balanceTone === 'error' ? (
        <View style={styles.errorBanner} testID="balance-error-banner">
          <WarningCircle color={color.error700} size={24} weight="bold" />
          <Text style={styles.bannerText}>
            A balance is exhausted. Message support to get connected again.
          </Text>
        </View>
      ) : null}
      <View style={styles.packageCard} testID="home-package-card">
        <View style={styles.cardHeader}>
          <Text style={styles.packageTitle}>DamDam eSIM</Text>
          {esimStatus === 'activated' ? (
            <View style={styles.activePill} testID="esim-active-pill">
              <CheckCircle color={color.success700} size={16} weight="bold" />
              <Text style={styles.activePillText}>Active</Text>
            </View>
          ) : null}
        </View>
        <Text style={styles.activeTitle}>
          {esimStatus === 'activated'
            ? 'Saudi Arabia data — active'
            : 'Saudi Arabia data is ready to activate.'}
        </Text>
        {remainingDataGb === null ? (
          <Text style={styles.inactiveText}>Balance unavailable</Text>
        ) : (
          <BalanceProgress
            kind="data"
            label="Mobile data"
            remaining={remainingDataGb}
            value={`${remainingDataGb.toFixed(2)} GB remaining`}
            percent={dataPercent}
            testID="data-balance-progress"
          />
        )}
        {pstnMinutesRemaining === null ? (
          <Text style={styles.inactiveText}>Minutes balance unavailable</Text>
        ) : (
          <BalanceProgress
            kind="minutes"
            label="Calling minutes"
            remaining={pstnMinutesRemaining}
            value={`${formatMinutes(pstnMinutesRemaining)} minutes remaining`}
            percent={minutesPercent}
            testID="minutes-balance-progress"
          />
        )}
        {remainingDataGb !== null || pstnMinutesRemaining !== null ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Message support on WhatsApp"
            onPress={() =>
              Linking.openURL(
                `https://wa.me/${SUPPORT_WHATSAPP_NUMBER}?text=${encodeURIComponent(
                  'Hello DamDam Support, I need help adding more data or calling minutes.',
                )}`,
              ).catch(() => undefined)
            }
            style={({pressed}) => [
              styles.supportButton,
              pressed && styles.pressedButton,
            ]}>
            <ChatCircle color={color.primary500} size={20} weight="bold" />
            <Text style={styles.supportButtonLabel}>Need more? Message support</Text>
          </Pressable>
        ) : null}
      </View>
      {onOpenCall ? (
        <Pressable onPress={onOpenCall} style={styles.callButton} testID="open-call-tab">
          <Phone color={color.white} size={24} weight="fill" />
          <Text style={styles.callButtonLabel}>Call family</Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

type BalanceTone = 'healthy' | 'warning' | 'error';

export function getHomeBalanceTone(
  dataRemainingPercent: number,
  pstnMinutesRemaining: number,
): BalanceTone {
  if (dataRemainingPercent <= 0 || pstnMinutesRemaining <= 0) return 'error';
  if (dataRemainingPercent < 20 || pstnMinutesRemaining < 5) return 'warning';
  return 'healthy';
}

function percentage(remaining: number | null, total: number | null): number {
  if (remaining === null || total === null || total <= 0) return 0;
  return Math.min(100, Math.max(0, (remaining / total) * 100));
}

export function getBalanceProgressTone(
  kind: 'data' | 'minutes',
  percent: number,
  remaining: number,
): BalanceTone {
  if (remaining <= 0) return 'error';
  if (kind === 'data' ? percent < 20 : remaining < 5) return 'warning';
  return 'healthy';
}

function progressColor(
  kind: 'data' | 'minutes',
  percent: number,
  remaining: number,
): string {
  const tone = getBalanceProgressTone(kind, percent, remaining);
  if (tone === 'error') return color.error700;
  if (tone === 'warning') return color.warning500;
  return color.success500;
}

function formatMinutes(minutes: number): string {
  return Number.isInteger(minutes) ? String(minutes) : minutes.toFixed(2);
}

function queueBreakdown(checkIns: number, sosAlerts: number): string {
  const pieces: string[] = [];
  if (checkIns > 0) pieces.push(`${checkIns} ${checkIns === 1 ? 'check-in' : 'check-ins'}`);
  if (sosAlerts > 0) {
    pieces.push(`${sosAlerts} SOS ${sosAlerts === 1 ? 'alert' : 'alerts'}`);
  }
  return pieces.join(' and ');
}

function BalanceProgress({
  kind,
  label,
  remaining,
  value,
  percent,
  testID,
}: {
  kind: 'data' | 'minutes';
  label: string;
  remaining: number;
  value: string;
  percent: number;
  testID: string;
}): React.JSX.Element {
  return (
    <View style={styles.balanceBlock}>
      <View style={styles.balanceHeading}>
        <Text style={styles.balanceLabel}>{label}</Text>
        <Text style={styles.dataValue}>{value}</Text>
      </View>
      <View
        accessibilityRole="progressbar"
        accessibilityValue={{min: 0, max: 100, now: percent}}
        style={styles.progressTrack}
        testID={testID}>
        <View
          style={[
            styles.progressFill,
            {
              backgroundColor: progressColor(kind, percent, remaining),
              width: `${percent}%`,
            },
          ]}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flexGrow: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingVertical: space.space6,
    gap: space.space6,
  },
  title: { ...typography.heading1, color: color.gray900 },
  checkInControl: { gap: space.space2 },
  checkInButton: {
    minHeight: 64,
    borderRadius: radius.button,
    backgroundColor: color.primary500,
    flexDirection: 'row',
    gap: space.space2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkInButtonLabel: {
    ...typography.bodyLarge,
    fontWeight: '600',
    color: color.white,
  },
  sosButton: {
    minHeight: 64,
    borderRadius: radius.button,
    backgroundColor: color.error700,
    flexDirection: 'row',
    gap: space.space2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sosButtonLabel: {...typography.bodyLarge, fontWeight: '700', color: color.white},
  disabledButton: { backgroundColor: color.gray300 },
  disabledButtonLabel: { color: color.gray500 },
  rateLimitHint: { ...typography.caption, color: color.gray600 },
  pressedButton: { opacity: 0.92, transform: [{scale: 0.98}] },
  successBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space3,
    backgroundColor: color.success100,
    borderLeftWidth: 4,
    borderLeftColor: color.success500,
    padding: space.space4,
  },
  queueBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space3,
    backgroundColor: color.gray100,
    padding: space.space4,
  },
  errorBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space3,
    backgroundColor: color.error100,
    borderLeftWidth: 4,
    borderLeftColor: color.error700,
    padding: space.space4,
  },
  bannerText: { ...typography.body, color: color.gray900 },
  queueBannerText: { color: color.gray700 },
  queueCopy: {flex: 1, gap: space.space1},
  queueDetail: {...typography.caption, color: color.gray600},
  lastCheckIn: { ...typography.body, color: color.gray600 },
  packageCard: {
    backgroundColor: color.white,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    padding: space.space4,
    gap: space.space2,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.space3,
  },
  packageTitle: { ...typography.heading2, color: color.gray900 },
  activePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space1,
    borderRadius: radius.card,
    backgroundColor: color.success100,
    paddingVertical: space.space1,
    paddingHorizontal: space.space2,
  },
  activePillText: {
    ...typography.caption,
    fontWeight: '600',
    color: color.success700,
  },
  activeTitle: { ...typography.bodyLarge, fontWeight: '600', color: color.gray900 },
  dataValue: { ...typography.numeral, color: color.gray900 },
  balanceBlock: {gap: space.space2, paddingVertical: space.space1},
  balanceHeading: {gap: space.space1},
  balanceLabel: {...typography.caption, fontWeight: '600', color: color.gray700},
  progressTrack: {
    height: 8,
    borderRadius: 4,
    backgroundColor: color.gray200,
    overflow: 'hidden',
  },
  progressFill: {height: 8, borderRadius: 4},
  warningBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space3,
    backgroundColor: color.warning100,
    borderLeftWidth: 4,
    borderLeftColor: color.warning500,
    padding: space.space4,
  },
  supportButton: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.space2,
  },
  supportButtonLabel: {
    ...typography.bodyLarge,
    fontWeight: '600',
    color: color.primary500,
  },
  inactiveText: { ...typography.body, color: color.gray600 },
  callButton: {
    minHeight: 64,
    borderRadius: radius.button,
    backgroundColor: color.primary500,
    flexDirection: 'row',
    gap: space.space2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  callButtonLabel: { ...typography.bodyLarge, fontWeight: '600', color: color.white },
});
