import React, { useCallback, useEffect, useState } from 'react';
import {useTranslation} from 'react-i18next';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { WebView, WebViewNavigation } from 'react-native-webview';
import {
  getPackageStatus,
  initializePurchase,
  PackagePaymentStatus,
  PurchaseCheckout,
} from '../../api/paymentClient';
import { PricingTier } from '../../api/pricingClient';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { color, minTouchTarget, space, typography } from '../../theme/tokens';
import { PackageSelectionScreen } from '../PackageSelection/PackageSelectionScreen';
import {i18n} from '../../i18n';

const POLL_INTERVAL_MS = 10_000;
const MAX_POLL_ATTEMPTS = 30;

interface Selection {
  tier: PricingTier;
  groupSize?: number;
}

interface RetailPurchaseFlowProps {
  accessToken: string;
  onPurchaseComplete?: (packageId: string) => void;
}

function failureReason(url: string): string | null {
  if (!/[?&]status=(failed|cancelled)/i.test(url)) {
    return null;
  }
  // Provider-controlled prose is intentionally not rendered. The status is
  // mapped to a first-party, locale-aware message.
  return i18n.t('purchase.failedDefault', {ns: 'payments'});
}

function SuccessScreen({
  checkout,
  status,
  onContinue,
}: {
  checkout: PurchaseCheckout;
  status: PackagePaymentStatus;
  onContinue?: (packageId: string) => void;
}) {
  const {t} = useTranslation(['payments', 'common']);
  return (
    <View style={[styles.screen, styles.centered]} testID="purchase-success-screen">
      <Text style={styles.successTitle}>{t('purchase.successful')}</Text>
      <Text style={styles.successBody}>
        {t('purchase.activePackage', {data: status.data_gb_remaining, minutes: status.pstn_minutes_remaining})}
      </Text>
      <Text style={styles.receiptNote}>{t('purchase.receipt')}</Text>
      <PrimaryButton
        label={t('actions.continue', {ns: 'common'})}
        onPress={() => onContinue?.(checkout.package_id)}
        testID="purchase-success-continue"
      />
    </View>
  );
}

export function RetailPurchaseFlow({
  accessToken,
  onPurchaseComplete,
}: RetailPurchaseFlowProps): React.JSX.Element {
  const {t} = useTranslation(['payments', 'common']);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [checkout, setCheckout] = useState<PurchaseCheckout | null>(null);
  const [confirmed, setConfirmed] = useState<PackagePaymentStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async (next: Selection) => {
    setSelection(next);
    setStarting(true);
    setError(null);
    setCheckout(null);
    setConfirmed(null);
    try {
      const result = await initializePurchase(
        accessToken,
        next.tier.id,
        next.groupSize,
      );
      setCheckout(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('purchase.startFailed'));
    } finally {
      setStarting(false);
    }
  }, [accessToken, t]);

  useEffect(() => {
    if (!checkout || error || confirmed) {
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    const poll = async () => {
      attempts += 1;
      try {
        const result = await getPackageStatus(accessToken, checkout.package_id);
        if (cancelled) return;
        if (result.status === 'active') {
          setConfirmed(result);
          return;
        }
        if (result.status === 'expired') {
          setError(t('purchase.expired'));
          return;
        }
      } catch {
        // A delayed webhook or a brief polling failure follows the same retry window.
      }
      if (!cancelled && attempts < MAX_POLL_ATTEMPTS) {
        timer = setTimeout(poll, POLL_INTERVAL_MS);
      } else if (!cancelled) {
        setError(t('purchase.delayed'));
      }
    };
    poll().catch(() => undefined);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [accessToken, checkout, confirmed, error, t]);

  if (checkout && confirmed) {
    return (
      <SuccessScreen
        checkout={checkout}
        status={confirmed}
        onContinue={onPurchaseComplete}
      />
    );
  }

  if (error && selection) {
    return (
      <View style={[styles.screen, styles.failure]} testID="payment-failure-screen">
        <Text style={styles.title}>{t('purchase.notCompleted')}</Text>
        <Banner tone="error" message={error} />
        <PrimaryButton
          label={t('actions.retry', {ns: 'common'})}
          onPress={() => start(selection).catch(() => undefined)}
          testID="payment-retry"
        />
        <Pressable
          accessibilityRole="button"
          onPress={() => {
            setSelection(null);
            setError(null);
            setCheckout(null);
          }}
          style={styles.backButton}
        >
          <Text style={styles.backLabel}>{t('purchase.chooseAnother')}</Text>
        </Pressable>
      </View>
    );
  }

  if (starting) {
    return (
      <View style={[styles.screen, styles.centered]} testID="payment-starting-screen">
        <ActivityIndicator size="large" color={color.primary500} />
        <Text style={styles.title}>{t('purchase.preparing')}</Text>
        <Text style={styles.body}>{t('purchase.preparingBody')}</Text>
      </View>
    );
  }

  if (checkout) {
    return (
      <View style={styles.screen} testID="payment-checkout-screen">
        <View style={styles.checkoutHeader}>
          <Text style={styles.title}>{t('purchase.complete')}</Text>
          <Text style={styles.body}>{t('purchase.methods')}</Text>
        </View>
        <WebView
          source={{ uri: checkout.checkout_url }}
          testID="payment-webview"
          onError={() => setError(t('purchase.checkoutLoadFailed'))}
          onHttpError={() => setError(t('purchase.checkoutLoadFailed'))}
          onNavigationStateChange={(navigation: WebViewNavigation): void => {
            const reason = failureReason(navigation.url);
            if (reason) setError(reason);
          }}
          style={styles.webview}
        />
      </View>
    );
  }

  return (
    <PackageSelectionScreen
      onSelectTier={(tier, groupSize) => start({ tier, groupSize }).catch(() => undefined)}
    />
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.gray50 },
  checkoutHeader: {
    paddingHorizontal: space.space5,
    paddingTop: space.space5,
    paddingBottom: space.space4,
    gap: space.space2,
    borderBottomWidth: 1,
    borderBottomColor: color.gray200,
    backgroundColor: color.white,
  },
  webview: { flex: 1, backgroundColor: color.white },
  centered: {
    justifyContent: 'center',
    paddingHorizontal: space.space5,
    gap: space.space4,
  },
  failure: { paddingHorizontal: space.space5, paddingTop: space.space10, gap: space.space6 },
  title: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  backButton: {
    minHeight: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backLabel: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
  successTitle: {
    fontSize: typography.display.fontSize,
    lineHeight: typography.display.lineHeight,
    fontWeight: typography.display.fontWeight,
    color: color.gray900,
    textAlign: 'center',
  },
  successBody: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray700,
    textAlign: 'center',
  },
  receiptNote: {
    marginBottom: space.space4,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
    textAlign: 'center',
  },
});
