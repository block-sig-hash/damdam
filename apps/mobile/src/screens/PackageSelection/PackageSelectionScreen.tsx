import React, { useEffect, useMemo, useState } from 'react';
import {
  AccessibilityInfo,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { PricingTier } from '../../api/pricingClient';
import { Banner } from '../../components/Banner/Banner';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import {
  color,
  minTouchTarget,
  radius,
  space,
  typography,
} from '../../theme/tokens';
import { usePackageTiers } from './usePackageTiers';

interface PackageSelectionScreenProps {
  onSelectTier: (tier: PricingTier, groupSize?: number) => void;
}

const TIER_ORDER: Record<string, number> = {
  Starter: 0,
  Basic: 1,
  Standard: 2,
  Family: 3,
};

function formatNaira(value: number): string {
  const rounded = Math.round(value);
  return `₦${String(rounded).replace(/\B(?=(\d{3})+(?!\d))/g, ',')}`;
}

function tierFeatures(tier: PricingTier): string[] {
  const suffix = tier.is_group_tier ? ' per pilgrim' : '';
  return [
    `${tier.data_gb} GB eSIM data${suffix}`,
    `${tier.pstn_minutes} Nigerian calling minutes${suffix}`,
    'Offline check-in and SOS tools',
  ];
}

function LoadingCards(): React.JSX.Element {
  return (
    <View testID="pricing-loading" style={styles.cardList}>
      {[0, 1, 2, 3].map((index) => (
        <View key={index} testID="pricing-skeleton-card" style={styles.skeletonCard}>
          <View style={styles.skeletonTitle} />
          <View style={styles.skeletonPrice} />
          <View style={styles.skeletonLine} />
        </View>
      ))}
    </View>
  );
}

interface FamilySelectorProps {
  tier: PricingTier | null;
  visible: boolean;
  reduceMotion: boolean;
  onDismiss: () => void;
  onContinue: (tier: PricingTier, groupSize: number) => void;
}

function FamilySelector({
  tier,
  visible,
  reduceMotion,
  onDismiss,
  onContinue,
}: FamilySelectorProps): React.JSX.Element | null {
  const minimum = tier?.min_group_size ?? 2;
  const maximum = tier?.max_group_size ?? 8;
  const [groupSizeText, setGroupSizeText] = useState(String(minimum));

  useEffect(() => {
    if (visible) {
      setGroupSizeText(String(minimum));
    }
  }, [minimum, visible]);

  if (!tier) {
    return null;
  }

  const groupSize = Number(groupSizeText);
  const valid = Number.isInteger(groupSize) && groupSize >= minimum && groupSize <= maximum;
  const total = valid ? tier.ngn_price * groupSize : 0;

  function adjust(amount: number) {
    const current = valid ? groupSize : minimum;
    const next = Math.min(maximum, Math.max(minimum, current + amount));
    setGroupSizeText(String(next));
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType={reduceMotion ? 'fade' : 'slide'}
      onRequestClose={onDismiss}
    >
      <View style={styles.modalBackdrop}>
        <View style={styles.modalSheet} testID="family-size-modal">
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Close group size selector"
            hitSlop={space.space2}
            onPress={onDismiss}
            style={styles.closeButton}
            testID="family-size-close"
          >
            <Text style={styles.closeLabel}>×</Text>
          </Pressable>
          <Text style={styles.modalTitle}>How many pilgrims?</Text>
          <Text style={styles.modalBody}>
            Family pricing is per person. Choose between {minimum} and {maximum} pilgrims.
          </Text>

          <Text style={styles.stepperFieldLabel}>Group size</Text>
          <View style={styles.stepper}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Remove one pilgrim"
              disabled={valid && groupSize === minimum}
              onPress={() => adjust(-1)}
              style={({ pressed }) => [
                styles.stepperButton,
                valid && groupSize === minimum && styles.stepperDisabled,
                pressed && styles.pressed,
              ]}
              testID="family-size-decrement"
            >
              <Text
                style={[
                  styles.stepperLabel,
                  valid && groupSize === minimum && styles.stepperLabelDisabled,
                ]}
              >
                −
              </Text>
            </Pressable>
            <TextInput
              accessibilityLabel="Family group size"
              keyboardType="number-pad"
              maxLength={1}
              onChangeText={(value) => setGroupSizeText(value.replace(/[^0-9]/g, ''))}
              selectTextOnFocus
              style={styles.groupSizeInput}
              testID="family-size-input"
              value={groupSizeText}
            />
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Add one pilgrim"
              disabled={valid && groupSize === maximum}
              onPress={() => adjust(1)}
              style={({ pressed }) => [
                styles.stepperButton,
                valid && groupSize === maximum && styles.stepperDisabled,
                pressed && styles.pressed,
              ]}
              testID="family-size-increment"
            >
              <Text
                style={[
                  styles.stepperLabel,
                  valid && groupSize === maximum && styles.stepperLabelDisabled,
                ]}
              >
                +
              </Text>
            </Pressable>
          </View>

          {!valid ? (
            <View accessibilityRole="alert" style={styles.inputErrorRow}>
              <Text style={styles.inputErrorIcon}>!</Text>
              <Text style={styles.inputError}>
                Enter a number from {minimum} to {maximum}.
              </Text>
            </View>
          ) : null}
          <Text style={styles.totalLabel}>Total package price</Text>
          <Text style={styles.totalValue} testID="family-total-price">
            {valid ? formatNaira(total) : '—'}
          </Text>
          <Text style={styles.perPersonPrice}>
            {formatNaira(tier.ngn_price)} per pilgrim
          </Text>

          <PrimaryButton
            disabled={!valid}
            label="Continue to payment"
            onPress={() => onContinue(tier, groupSize)}
            testID="family-size-continue"
          />
        </View>
      </View>
    </Modal>
  );
}

/** US-08 / docs/frontend-mobile.md §8.3, built from design-system.md tokens. */
export function PackageSelectionScreen({
  onSelectTier,
}: PackageSelectionScreenProps): React.JSX.Element {
  const { status, tiers, errorMessage, retry } = usePackageTiers();
  const [familyTier, setFamilyTier] = useState<PricingTier | null>(null);
  const [includedOpen, setIncludedOpen] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setReduceMotion).catch(() => undefined);
    const subscription = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      setReduceMotion,
    );
    return () => subscription.remove();
  }, []);

  const visibleTiers = useMemo(
    () =>
      [...tiers].sort(
        (left, right) =>
          (TIER_ORDER[left.name] ?? 4) - (TIER_ORDER[right.name] ?? 4),
      ),
    [tiers],
  );

  function chooseTier(tier: PricingTier) {
    if (tier.is_group_tier) {
      setFamilyTier(tier);
      return;
    }
    onSelectTier(tier);
  }

  if (status === 'error') {
    return (
      <View style={[styles.screen, styles.errorScreen]} testID="pricing-error-screen">
        <Text style={styles.title}>Choose your package</Text>
        <Banner
          message={errorMessage ?? 'Package prices are unavailable. Please try again.'}
          tone="error"
        />
        <PrimaryButton
          label="Try again"
          onPress={() => retry().catch(() => undefined)}
          testID="pricing-retry"
        />
      </View>
    );
  }

  return (
    <>
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        style={styles.screen}
        testID="package-selection-screen"
      >
        <Text style={styles.eyebrow}>Stay connected in Saudi Arabia</Text>
        <Text style={styles.title}>Choose your package</Text>
        <Text style={styles.subtitle}>
          Clear Naira pricing, with data and calls included.
        </Text>

        {status === 'loading' ? (
          <LoadingCards />
        ) : (
          <View style={styles.cardList}>
            {visibleTiers.map((tier) => (
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Choose ${tier.name} package`}
                key={tier.id}
                onPress={() => chooseTier(tier)}
                style={({ pressed }) => [
                  styles.tierCard,
                  tier.is_group_tier && styles.familyCard,
                  pressed && styles.pressed,
                ]}
                testID={`tier-${tier.name}`}
              >
                <View style={styles.cardHeading}>
                  <Text style={styles.tierName}>{tier.name}</Text>
                  {tier.name === 'Standard' ? (
                    <View style={styles.recommendedBadge}>
                      <Text style={styles.recommendedText}>Recommended</Text>
                    </View>
                  ) : null}
                </View>
                <Text style={styles.price}>
                  {tier.is_group_tier ? 'From ' : ''}{formatNaira(tier.ngn_price)}
                </Text>
                {tier.is_group_tier ? (
                  <Text style={styles.priceCaption}>per pilgrim · choose 2–8 people</Text>
                ) : null}
                <View style={styles.featureList}>
                  {tierFeatures(tier).map((feature) => (
                    <Text key={feature} style={styles.feature}>•  {feature}</Text>
                  ))}
                </View>
              </Pressable>
            ))}
          </View>
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityState={{ expanded: includedOpen }}
          onPress={() => setIncludedOpen((open) => !open)}
          style={({ pressed }) => [styles.accordionTrigger, pressed && styles.pressed]}
          testID="whats-included-toggle"
        >
          <Text style={styles.accordionLabel}>What's included</Text>
          <Text style={styles.accordionSymbol}>{includedOpen ? '−' : '+'}</Text>
        </Pressable>
        {includedOpen ? (
          <View style={styles.includedPanel} testID="whats-included-content">
            <Text style={styles.includedHeading}>Every package includes</Text>
            <Text style={styles.includedText}>•  eSIM data for Saudi Arabia</Text>
            <Text style={styles.includedText}>•  Calls with your Nigerian caller ID</Text>
            <Text style={styles.includedText}>•  Offline-ready check-in and SOS tools</Text>
          </View>
        ) : null}
      </ScrollView>

      <FamilySelector
        onContinue={(tier, groupSize) => {
          setFamilyTier(null);
          onSelectTier(tier, groupSize);
        }}
        onDismiss={() => setFamilyTier(null)}
        reduceMotion={reduceMotion}
        tier={familyTier}
        visible={familyTier !== null}
      />
    </>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.gray50 },
  scrollContent: {
    paddingHorizontal: space.space5,
    paddingTop: space.space8,
    paddingBottom: space.space12,
  },
  eyebrow: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
  title: {
    marginTop: space.space1,
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    fontWeight: typography.heading1.fontWeight,
    color: color.gray900,
  },
  subtitle: {
    marginTop: space.space2,
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray700,
  },
  cardList: { gap: space.space4, marginTop: space.space6 },
  tierCard: {
    minHeight: space.space16,
    padding: space.space4,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    backgroundColor: color.white,
    shadowColor: color.gray900,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: space.space1,
    elevation: 2,
  },
  familyCard: { borderLeftWidth: space.space1, borderLeftColor: color.accent500 },
  pressed: { opacity: 0.92, transform: [{ scale: 0.98 }] },
  cardHeading: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.space3,
  },
  tierName: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  recommendedBadge: {
    paddingHorizontal: space.space3,
    paddingVertical: space.space1,
    borderRadius: radius.card,
    backgroundColor: color.accent500,
  },
  recommendedText: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.gray900,
  },
  price: {
    marginTop: space.space2,
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.primary700,
  },
  priceCaption: {
    marginTop: space.space1,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
  },
  featureList: { gap: space.space2, marginTop: space.space4 },
  feature: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  accordionTrigger: {
    minHeight: minTouchTarget,
    marginTop: space.space6,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  accordionLabel: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    fontWeight: '600',
    color: color.primary500,
  },
  accordionSymbol: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    color: color.primary500,
  },
  includedPanel: {
    padding: space.space4,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    backgroundColor: color.white,
    gap: space.space2,
  },
  includedHeading: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.gray900,
  },
  includedText: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  errorScreen: {
    paddingHorizontal: space.space5,
    paddingTop: space.space10,
    gap: space.space6,
  },
  skeletonCard: {
    minHeight: 180,
    padding: space.space4,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    backgroundColor: color.white,
    gap: space.space4,
  },
  skeletonTitle: {
    width: '45%',
    height: space.space6,
    borderRadius: radius.button,
    backgroundColor: color.gray200,
  },
  skeletonPrice: {
    width: '60%',
    height: space.space8,
    borderRadius: radius.button,
    backgroundColor: color.gray100,
  },
  skeletonLine: {
    width: '85%',
    height: space.space5,
    borderRadius: radius.button,
    backgroundColor: color.gray100,
  },
  modalBackdrop: {
    flex: 1,
    justifyContent: 'flex-end',
    backgroundColor: 'rgba(20, 24, 26, 0.45)',
  },
  modalSheet: {
    paddingHorizontal: space.space5,
    paddingTop: space.space5,
    paddingBottom: space.space10,
    borderTopLeftRadius: radius.card,
    borderTopRightRadius: radius.card,
    backgroundColor: color.white,
  },
  closeButton: {
    minWidth: minTouchTarget,
    minHeight: minTouchTarget,
    alignSelf: 'flex-end',
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeLabel: {
    fontSize: typography.heading1.fontSize,
    lineHeight: typography.heading1.lineHeight,
    color: color.gray700,
  },
  modalTitle: {
    fontSize: typography.heading2.fontSize,
    lineHeight: typography.heading2.lineHeight,
    fontWeight: typography.heading2.fontWeight,
    color: color.gray900,
  },
  modalBody: {
    marginTop: space.space2,
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
  },
  stepperFieldLabel: {
    marginTop: space.space5,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.gray700,
    textAlign: 'center',
  },
  stepper: {
    marginTop: space.space2,
    marginBottom: space.space6,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.space4,
  },
  stepperButton: {
    width: minTouchTarget,
    height: minTouchTarget,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: color.primary500,
    borderRadius: radius.button,
    backgroundColor: color.white,
  },
  stepperDisabled: { borderColor: color.gray300, backgroundColor: color.gray100 },
  stepperLabel: {
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.primary500,
  },
  stepperLabelDisabled: { color: color.gray500 },
  groupSizeInput: {
    width: space.space16,
    minHeight: 52,
    borderWidth: 2,
    borderColor: color.primary500,
    borderRadius: radius.button,
    textAlign: 'center',
    fontSize: typography.numeral.fontSize,
    lineHeight: typography.numeral.lineHeight,
    fontWeight: typography.numeral.fontWeight,
    color: color.gray900,
  },
  inputErrorRow: {
    marginBottom: space.space3,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.space2,
  },
  inputErrorIcon: {
    width: space.space5,
    height: space.space5,
    borderRadius: radius.card,
    backgroundColor: color.error700,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '700',
    color: color.white,
    textAlign: 'center',
  },
  inputError: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: '600',
    color: color.error700,
  },
  totalLabel: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray700,
    textAlign: 'center',
  },
  totalValue: {
    marginTop: space.space1,
    fontSize: typography.display.fontSize,
    lineHeight: typography.display.lineHeight,
    fontWeight: typography.display.fontWeight,
    color: color.primary700,
    textAlign: 'center',
  },
  perPersonPrice: {
    marginBottom: space.space6,
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
    textAlign: 'center',
  },
});
