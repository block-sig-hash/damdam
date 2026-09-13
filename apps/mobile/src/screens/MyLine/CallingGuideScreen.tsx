import React from 'react';
import { useTranslation } from 'react-i18next';
import { Platform, ScrollView, StyleSheet, Text, View } from 'react-native';
import type { LineDetail } from '../../api/lineClient';
import { Banner } from '../../components/Banner/Banner';
import { SecondaryButton } from '../../components/SecondaryButton/SecondaryButton';
import { color, radius, space, typography } from '../../theme/tokens';

interface CallingGuideScreenProps {
  line: LineDetail;
  onBack: () => void;
}

/**
 * Choosing this line for calls and data on a phone that holds more than one
 * (US-38, AC-38.4).
 *
 * Guidance only, and that is a deliberate limit rather than a gap. Neither
 * platform lets an app choose which SIM places a call, set the default data
 * line, or observe which one the customer picked. An app that opened the dialer
 * and then claimed the call went out on this line would be asserting three
 * things it cannot see — which SIM was selected, whether the line was attached,
 * and whether a call happened at all — and the approved calling amendment names
 * exactly that inference as forbidden.
 *
 * So this screen tells the customer where the setting lives on their own phone
 * and stops. The one thing it adds is the state the app *does* know: whether
 * the carrier says this line carries voice at all, because sending somebody into
 * their settings to select a data-only line for calls wastes their time.
 */
export function CallingGuideScreen({
  line,
  onBack,
}: CallingGuideScreenProps): React.JSX.Element {
  const { t } = useTranslation('line');
  const steps = Platform.OS === 'ios' ? IOS_STEPS : ANDROID_STEPS;

  return (
    <ScrollView contentContainerStyle={styles.screen} testID="calling-guide">
      <Text style={styles.title}>{t('guide.title')}</Text>

      {line.calling.native_available ? (
        <Banner
          tone="info"
          testID="calling-guide-available"
          message={t('guide.availableForVoice')}
        />
      ) : (
        <Banner
          tone="warning"
          testID="calling-guide-unavailable"
          message={t(
            `calling.nativeUnavailable.${line.calling.native_unavailable_reason ?? 'unknown'}`,
            { defaultValue: t('calling.nativeUnavailable.unknown') },
          )}
        />
      )}

      {line.assigned_number ? (
        <Text style={styles.body} testID="calling-guide-number">
          {t('guide.thisLineIs', { number: line.assigned_number.e164 })}
        </Text>
      ) : null}

      <View style={styles.card}>
        <Text style={styles.cardLabel}>{t('guide.callsTitle')}</Text>
        {steps.calls.map((key, index) => (
          <Text key={key} style={styles.step}>
            {`${index + 1}. ${t(key)}`}
          </Text>
        ))}
      </View>

      <View style={styles.card}>
        <Text style={styles.cardLabel}>{t('guide.dataTitle')}</Text>
        {steps.data.map((key, index) => (
          <Text key={key} style={styles.step}>
            {`${index + 1}. ${t(key)}`}
          </Text>
        ))}
      </View>

      {/*
        The sentence that keeps the whole screen honest. Opening the dialer is
        not a call, a chosen SIM, or an attached network — and the app is not
        able to tell the customer which of those happened.
      */}
      <Text style={styles.footnote} testID="calling-guide-caveat">
        {t('guide.caveat')}
      </Text>

      <SecondaryButton
        label={t('guide.back')}
        onPress={onBack}
        testID="calling-guide-back"
      />
    </ScrollView>
  );
}

const IOS_STEPS = {
  calls: [
    'guide.ios.calls.openSettings',
    'guide.ios.calls.openCellular',
    'guide.ios.calls.chooseLine',
    'guide.ios.calls.setDefaultVoice',
  ],
  data: ['guide.ios.data.openCellularData', 'guide.ios.data.chooseLine'],
};

const ANDROID_STEPS = {
  calls: [
    'guide.android.calls.openSettings',
    'guide.android.calls.openSims',
    'guide.android.calls.chooseCallsSim',
  ],
  data: ['guide.android.data.openSims', 'guide.android.data.chooseDataSim'],
};

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
    gap: space.space2,
  },
  cardLabel: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray700,
  },
  body: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  step: {
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
