import { MapPin } from 'phosphor-react-native';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { PrimaryButton } from '../../components/PrimaryButton/PrimaryButton';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { ARRIVAL_NOTIFICATION_COPY } from '../../services/arrivalPrompts';
import { color, radius, space, typography } from '../../theme/tokens';

interface EsimActivationPromptScreenProps {
  activationPath: 'single_tap' | 'manual';
  onActivate: () => void;
  onManualGuide: () => void;
  activating?: boolean;
}

export function EsimActivationPromptScreen({
  activationPath,
  onActivate,
  onManualGuide,
  activating = false,
}: EsimActivationPromptScreenProps): React.JSX.Element {
  const manual = activationPath === 'manual';
  return (
    <View style={styles.screen} testID="esim-arrival-prompt">
      <View style={styles.iconCard}>
        <MapPin color={color.info500} size={32} weight="bold" />
      </View>
      <Text style={styles.title}>You’ve arrived</Text>
      <Text style={styles.message}>{ARRIVAL_NOTIFICATION_COPY}</Text>
      <View style={styles.actions}>
        <PrimaryButton
          label={manual ? 'Show activation guide' : 'Activate now'}
          onPress={manual ? onManualGuide : onActivate}
          loading={activating}
          testID="arrival-activate"
        />
        {!manual ? (
          <SecondaryButton label="Use manual guide" onPress={onManualGuide} />
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: color.gray50,
    paddingHorizontal: space.space5,
    paddingVertical: space.space10,
    gap: space.space6,
  },
  iconCard: {
    width: space.space16,
    height: space.space16,
    borderWidth: 1,
    borderColor: color.gray200,
    borderRadius: radius.card,
    backgroundColor: color.info100,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: { ...typography.heading1, color: color.gray900 },
  message: { ...typography.bodyLarge, color: color.gray700 },
  actions: { marginTop: 'auto', gap: space.space3 },
});
