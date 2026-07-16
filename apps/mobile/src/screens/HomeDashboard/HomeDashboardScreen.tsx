import { CheckCircle, Clock, Phone, Siren, WarningCircle } from 'phosphor-react-native';
import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { shouldShowDateActivationBanner } from '../../services/arrivalPrompts';
import { color, radius, space, typography } from '../../theme/tokens';
import { EsimActivationBanner } from './EsimActivationBanner';

interface HomeDashboardScreenProps {
  departureDate: string | null;
  esimStatus: 'issued' | 'downloaded' | 'activated' | 'not_issued';
  remainingDataGb: number;
  onActivateEsim: () => void;
  now?: Date;
  onOpenCall?: () => void;
  onCheckIn?: () => Promise<'sent' | 'queued'>;
  lastCheckInAt?: string | null;
  queuedCheckIns?: number;
  onOpenSOS?: () => void;
}

export function HomeDashboardScreen({
  departureDate,
  esimStatus,
  remainingDataGb,
  onActivateEsim,
  now = new Date(),
  onOpenCall,
  onCheckIn,
  lastCheckInAt = null,
  queuedCheckIns = 0,
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
      {queuedCheckIns > 0 ? (
        <View style={styles.queueBanner} testID="queued-events-indicator">
          <Clock color={color.gray700} size={24} weight="bold" />
          <Text style={[styles.bannerText, styles.queueBannerText]}>
            {queuedCheckIns} {queuedCheckIns === 1 ? 'check-in' : 'check-ins'} waiting to send
          </Text>
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
        {esimStatus === 'activated' ? (
          <>
            <Text style={styles.activeTitle}>Saudi Arabia data — active</Text>
            <Text style={styles.dataValue}>{remainingDataGb.toFixed(2)} GB</Text>
            <Text style={styles.dataLabel}>remaining</Text>
          </>
        ) : (
          <Text style={styles.inactiveText}>Saudi Arabia data is ready to activate.</Text>
        )}
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
  dataLabel: { ...typography.body, color: color.gray600 },
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
