import {
  ChatCircle,
  CheckCircle,
  Phone,
  WarningCircle,
} from 'phosphor-react-native';
import React, { useState } from 'react';
import {useTranslation} from 'react-i18next';
import {Linking, Pressable, ScrollView, StyleSheet, Text, View} from 'react-native';
import {SUPPORT_WHATSAPP_NUMBER} from '../../config/env';
import { shouldShowDateActivationBanner } from '../../services/activationLinks';
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
}: HomeDashboardScreenProps): React.JSX.Element {
  const {t} = useTranslation('home');
  const [dismissedThisSession, setDismissedThisSession] = useState(false);
  const showBanner =
    !dismissedThisSession &&
    shouldShowDateActivationBanner(departureDate, esimStatus, now);
  const dataPercent = percentage(remainingDataGb, dataTotalGb);
  const minutesPercent = percentage(pstnMinutesRemaining, pstnMinutesTotal);
  const balanceTone =
    remainingDataGb === null || pstnMinutesRemaining === null
      ? 'healthy'
      : getHomeBalanceTone(dataPercent, pstnMinutesRemaining);

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>{t('dashboard.title')}</Text>
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
            {t('dashboard.lowBalance')}
          </Text>
        </View>
      ) : null}
      {remainingDataGb !== null && balanceTone === 'error' ? (
        <View style={styles.errorBanner} testID="balance-error-banner">
          <WarningCircle color={color.error700} size={24} weight="bold" />
          <Text style={styles.bannerText}>
            {t('dashboard.exhaustedBalance')}
          </Text>
        </View>
      ) : null}
      <View style={styles.packageCard} testID="home-package-card">
        <View style={styles.cardHeader}>
          <Text style={styles.packageTitle}>DamDam eSIM</Text>
          {esimStatus === 'activated' ? (
            <View style={styles.activePill} testID="esim-active-pill">
              <CheckCircle color={color.success700} size={16} weight="bold" />
              <Text style={styles.activePillText}>{t('dashboard.active')}</Text>
            </View>
          ) : null}
        </View>
        <Text style={styles.activeTitle}>
          {esimStatus === 'activated'
            ? t('dashboard.dataActive')
            : t('dashboard.dataReady')}
        </Text>
        {remainingDataGb === null ? (
          <Text style={styles.inactiveText}>{t('dashboard.balanceUnavailable')}</Text>
        ) : (
          <BalanceProgress
            kind="data"
            label={t('dashboard.mobileData')}
            remaining={remainingDataGb}
            value={t('dashboard.dataRemaining', {amount: remainingDataGb.toFixed(2)})}
            percent={dataPercent}
            testID="data-balance-progress"
          />
        )}
        {pstnMinutesRemaining === null ? (
          <Text style={styles.inactiveText}>{t('dashboard.minutesUnavailable')}</Text>
        ) : (
          <BalanceProgress
            kind="minutes"
            label={t('dashboard.callingMinutes')}
            remaining={pstnMinutesRemaining}
            value={t('dashboard.minutesRemaining', {amount: formatMinutes(pstnMinutesRemaining)})}
            percent={minutesPercent}
            testID="minutes-balance-progress"
          />
        )}
        {remainingDataGb !== null || pstnMinutesRemaining !== null ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={t('dashboard.supportAccessibility')}
            onPress={() =>
              Linking.openURL(
                `https://wa.me/${SUPPORT_WHATSAPP_NUMBER}?text=${encodeURIComponent(
                  t('dashboard.supportMessage'),
                )}`,
              ).catch(() => undefined)
            }
            style={({pressed}) => [
              styles.supportButton,
              pressed && styles.pressedButton,
            ]}>
            <ChatCircle color={color.primary500} size={20} weight="bold" />
            <Text style={styles.supportButtonLabel}>{t('dashboard.needMore')}</Text>
          </Pressable>
        ) : null}
      </View>
      {onOpenCall ? (
        <Pressable onPress={onOpenCall} style={styles.callButton} testID="open-call-tab">
          <Phone color={color.white} size={24} weight="fill" />
          <Text style={styles.callButtonLabel}>{t('dashboard.callFamily')}</Text>
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
  pressedButton: { opacity: 0.92, transform: [{scale: 0.98}] },
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
