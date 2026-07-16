import { CheckCircle, Phone } from 'phosphor-react-native';
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
}

export function HomeDashboardScreen({
  departureDate,
  esimStatus,
  remainingDataGb,
  onActivateEsim,
  now = new Date(),
  onOpenCall,
}: HomeDashboardScreenProps): React.JSX.Element {
  const [dismissedThisSession, setDismissedThisSession] = useState(false);
  const showBanner =
    !dismissedThisSession &&
    shouldShowDateActivationBanner(departureDate, esimStatus, now);

  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Home</Text>
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
