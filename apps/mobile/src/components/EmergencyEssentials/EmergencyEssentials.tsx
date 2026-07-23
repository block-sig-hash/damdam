import React from 'react';
import {useTranslation} from 'react-i18next';
import { FirstAidKit, PhoneCall, Translate, WhatsappLogo } from 'phosphor-react-native';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { SUPPORT_WHATSAPP_NUMBER } from '../../config/env';
import { EMERGENCY_PHRASES } from '../../content/emergencyEssentials';
import { color, minTouchTarget, radius, space, typography } from '../../theme/tokens';
import { useEmergencyContact } from './useEmergencyContact';

interface EmergencyEssentialsProps {
  accessToken: string;
}

/**
 * US-12. A self-contained, reusable section — rendered on Screen 17
 * (pre-departure, AC-12.1) today, and designed to drop into the SOS
 * screen unchanged once that's built (AC-12.4, deferred to US-16; see
 * the PR description for why that's a forward-compatibility decision,
 * not a skipped requirement).
 */
export function EmergencyEssentials({
  accessToken,
}: EmergencyEssentialsProps): React.JSX.Element {
  const {t} = useTranslation('safety');
  const contact = useEmergencyContact(accessToken);

  return (
    <View style={styles.card} testID="emergency-essentials">
      <View style={styles.header}>
        <FirstAidKit color={color.primary500} size={20} weight="bold" />
        <Text style={styles.headerText}>{t('essentials.title')}</Text>
      </View>

      {contact?.hto_operator_phone_number ? (
        <ContactRow
          icon={<PhoneCall color={color.primary500} size={24} weight="bold" />}
          label={contact.hto_operator_name ?? t('essentials.htoOperator')}
          value={contact.hto_operator_phone_number}
          onPress={() =>
            Linking.openURL(`tel:${contact.hto_operator_phone_number}`).catch(() => undefined)
          }
          testID="emergency-hto-contact"
        />
      ) : null}

      <ContactRow
        icon={<WhatsappLogo color={color.primary500} size={24} weight="bold" />}
        label={t('essentials.support')}
        value={`+${SUPPORT_WHATSAPP_NUMBER}`}
        onPress={() =>
          Linking.openURL(`https://wa.me/${SUPPORT_WHATSAPP_NUMBER}`).catch(() => undefined)
        }
        testID="emergency-support-contact"
      />

      <View style={[styles.header, styles.phrasesHeader]}>
        <Translate color={color.primary500} size={20} weight="bold" />
        <Text style={styles.headerText}>{t('essentials.phrasesTitle')}</Text>
      </View>
      {EMERGENCY_PHRASES.map(phrase => (
        <View
          key={phrase.key}
          style={styles.phraseRow}
          testID={`emergency-phrase-${phrase.key}`}
        >
          <Text style={styles.phraseEnglish}>{t(`phrases.${phrase.key}`)}</Text>
          {/* design-system.md §2 "Bilingual / RTL content": system-font
              fallback (no Arabic glyphs in the bundled Inter asset) plus
              an explicit writingDirection, not the Inter/LTR default —
              see the phraseArabic style below. */}
          <Text style={styles.phraseArabic}>{phrase.arabic}</Text>
          <Text style={styles.phraseTransliteration}>{phrase.transliteration}</Text>
        </View>
      ))}
    </View>
  );
}

interface ContactRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  onPress: () => void;
  testID: string;
}

function ContactRow({ icon, label, value, onPress, testID }: ContactRowProps): React.JSX.Element {
  return (
    <Pressable
      onPress={onPress}
      testID={testID}
      accessibilityRole="button"
      style={({ pressed }) => [styles.contactRow, pressed && styles.contactRowPressed]}
    >
      {icon}
      <View style={styles.contactText}>
        <Text style={styles.contactLabel}>{label}</Text>
        <Text style={styles.contactValue}>{value}</Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: color.white,
    borderColor: color.gray200,
    borderWidth: 1,
    borderRadius: radius.card,
    padding: space.space4,
    marginTop: space.space6,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space2,
  },
  phrasesHeader: {
    marginTop: space.space4,
  },
  headerText: {
    fontSize: typography.heading3.fontSize,
    lineHeight: typography.heading3.lineHeight,
    fontWeight: typography.heading3.fontWeight,
    color: color.gray900,
  },
  contactRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.space3,
    minHeight: minTouchTarget,
    marginTop: space.space3,
  },
  contactRowPressed: {
    opacity: 0.7,
  },
  contactText: { flex: 1 },
  contactLabel: {
    fontSize: typography.body.fontSize,
    lineHeight: typography.body.lineHeight,
    color: color.gray900,
  },
  contactValue: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
  },
  phraseRow: {
    marginTop: space.space3,
    paddingTop: space.space3,
    borderTopWidth: 1,
    borderTopColor: color.gray100,
  },
  phraseEnglish: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    fontWeight: typography.caption.fontWeight,
    color: color.gray600,
  },
  phraseArabic: {
    fontSize: typography.bodyLarge.fontSize,
    lineHeight: typography.bodyLarge.lineHeight,
    color: color.gray900,
    textAlign: 'right',
    writingDirection: 'rtl',
    marginTop: space.space1,
  },
  phraseTransliteration: {
    fontSize: typography.caption.fontSize,
    lineHeight: typography.caption.lineHeight,
    color: color.gray600,
    marginTop: space.space1,
  },
});
