import React from 'react';
import {useTranslation} from 'react-i18next';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { useActivationRedeem } from './useActivationRedeem';
import type { ActivationRedemption } from '../../api/activationClient';

interface ActivationSuccessScreenProps {
  accessToken: string;
  activationCode: string;
  onContinue: (redemption: ActivationRedemption) => void;
}

/**
 * US-07 / prd.md §4.2 — AC-07.4, AC-07.5, AC-07.6. Screen 14 of the
 * onboarding flow (docs/frontend-mobile.md §8.1), reached at the end
 * of Flow B (§8.2) for both new and existing pilgrims. "Continue"
 * hands off to the same post-package Home Dashboard Flow A converges
 * on — Purchase Success and Home Dashboard aren't built yet (US-08+),
 * so `onContinue` is a seam for that screen once it exists, not a
 * hardcoded destination here.
 */
export function ActivationSuccessScreen({
  accessToken,
  activationCode,
  onContinue,
}: ActivationSuccessScreenProps): React.JSX.Element {
  const {t} = useTranslation(['auth', 'common']);
  const { status, result, errorMessage, retry } = useActivationRedeem({
    accessToken,
    activationCode,
  });

  if (status === 'redeeming') {
    return (
      <View style={[styles.screen, styles.centered]} testID="activation-redeeming">
        <ActivityIndicator color={color.primary500} size="large" />
        <Text style={styles.redeemingText}>{t('activation.attaching')}</Text>
      </View>
    );
  }

  if (status === 'error') {
    return (
      <View style={styles.screen}>
        <Text style={styles.title}>{t('activation.attachFailed')}</Text>
        <View style={styles.bannerSpacing}>
          <Banner
            tone="error"
            message={errorMessage ?? t('errors.generic')}
            testID="activation-redeem-error"
          />
        </View>
        <View style={styles.footer}>
          <PrimaryButton
            testID="activation-redeem-retry"
            label={t('actions.tryAgain', {ns: 'common'})}
            onPress={retry}
          />
        </View>
      </View>
    );
  }

  return (
    <View style={styles.screen} testID="activation-success">
      <Text style={styles.eyebrow}>{t('activation.activated')}</Text>
      <Text style={styles.headline}>{t('activation.allSet')}</Text>
      <Text style={styles.subtitle}>
        {t('activation.ready', {tier: result?.pricing_tier_name})}
      </Text>

      <View style={styles.summaryCard}>
        <Text style={styles.summaryValue}>{t('activation.dataAmount', {amount: result?.data_gb_total})}</Text>
        <Text style={styles.summaryLabel}>{t('activation.data')}</Text>
        <Text style={styles.summaryValue}>{t('activation.minutesAmount', {amount: result?.pstn_minutes_total})}</Text>
        <Text style={styles.summaryLabel}>{t('activation.calling')}</Text>
      </View>

      <View style={styles.footer}>
        <PrimaryButton
          testID="activation-success-continue"
          label={t('actions.continue', {ns: 'common'})}
          onPress={() => result && onContinue(result)}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
  },
  centered: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  redeemingText: {
    marginTop: space.space4,
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray700,
  },
  eyebrow: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.success700,
  },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  headline: {
    marginTop: space.space1,
    fontSize: typography.display.fontSize,
    lineHeight: typography.display.lineHeight,
    fontWeight: typography.display.fontWeight,
    color: color.gray900,
  },
  subtitle: {
    marginTop: space.space3,
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray700,
  },
  summaryCard: {
    marginTop: space.space8,
    padding: space.space5,
    borderRadius: radius.card,
    backgroundColor: color.success100,
  },
  summaryValue: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.success700,
  },
  summaryLabel: {
    marginBottom: space.space3,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  bannerSpacing: {
    marginTop: space.space4,
  },
  footer: {
    marginTop: space.space8,
  },
});
