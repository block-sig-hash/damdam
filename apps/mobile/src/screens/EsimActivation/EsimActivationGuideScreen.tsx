import { ImageSquare } from 'phosphor-react-native';
import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';
import { activationGuideFor } from './activationGuides';

interface EsimActivationGuideScreenProps {
  platform: 'ios' | 'android';
  deviceModel: string;
  onShowQrCode: () => void;
  onConfirmActivated: () => void;
  confirming?: boolean;
}

export function EsimActivationGuideScreen({
  platform,
  deviceModel,
  onShowQrCode,
  onConfirmActivated,
  confirming = false,
}: EsimActivationGuideScreenProps): React.JSX.Element {
  const guide = activationGuideFor(platform, deviceModel);
  return (
    <ScrollView contentContainerStyle={styles.screen}>
      <Text style={styles.title}>Activate your eSIM</Text>
      <Text style={styles.intro}>Follow these steps for {guide.name}. Keep DamDam open.</Text>
      {guide.contentStatus === 'placeholder' ? (
        <View style={styles.contentNotice} testID="android-guide-content-gap">
          <Text style={styles.contentNoticeText}>
            Device-specific screenshots are being verified on real phones. These generic steps are safe to use now.
          </Text>
        </View>
      ) : null}
      <View style={styles.steps}>
        {guide.steps.map((step, index) => (
          <View key={step.instruction} style={styles.stepCard} testID={`activation-step-${index + 1}`}>
            <View style={styles.stepHeader}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>{index + 1}</Text>
              </View>
              <Text style={styles.stepInstruction}>{step.instruction}</Text>
            </View>
            <View style={styles.screenshotPlaceholder}>
              <ImageSquare color={color.gray700} size={32} weight="regular" />
              <Text style={styles.screenshotLabel}>{step.screenshotLabel}</Text>
            </View>
          </View>
        ))}
      </View>
      <SecondaryButton label="Show my QR code" onPress={onShowQrCode} />
      <PrimaryButton
        label="I've activated it"
        onPress={onConfirmActivated}
        loading={confirming}
        testID="confirm-esim-activated"
      />
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
  intro: { ...typography.bodyLarge, color: color.gray700 },
  contentNotice: {
    borderLeftWidth: 4,
    borderLeftColor: color.info500,
    borderRadius: radius.button,
    backgroundColor: color.info100,
    padding: space.space4,
  },
  contentNoticeText: { ...typography.body, color: color.gray900 },
  steps: { gap: space.space4 },
  stepCard: {
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    backgroundColor: color.white,
    padding: space.space4,
    gap: space.space4,
  },
  stepHeader: { flexDirection: 'row', alignItems: 'center', gap: space.space3 },
  stepNumber: {
    width: space.space8,
    height: space.space8,
    borderRadius: radius.card,
    backgroundColor: color.primary100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepNumberText: { ...typography.body, fontWeight: '600', color: color.primary700 },
  stepInstruction: { ...typography.bodyLarge, color: color.gray900, flex: 1 },
  screenshotPlaceholder: {
    minHeight: 160,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.button,
    backgroundColor: color.gray100,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.space2,
    padding: space.space4,
  },
  screenshotLabel: { ...typography.caption, color: color.gray600 },
});
