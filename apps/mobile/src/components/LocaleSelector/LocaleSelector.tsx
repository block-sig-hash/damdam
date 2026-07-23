import React from 'react';
import {Pressable, StyleSheet, Text, View} from 'react-native';
import {useTranslation} from 'react-i18next';

import {AppLocale, setAppLocale} from '../../i18n';
import {color, minTouchTarget, radius, space, typography} from '../../theme/tokens';

export function LocaleSelector(): React.JSX.Element {
  const {i18n, t} = useTranslation('common');
  const current: AppLocale = i18n.resolvedLanguage === 'fr' ? 'fr' : 'en';

  return (
    <View accessibilityLabel={t('language.label')} accessibilityRole="radiogroup" style={styles.row}>
      {(['en', 'fr'] as const).map(locale => (
        <Pressable
          accessibilityRole="radio"
          accessibilityState={{checked: current === locale}}
          key={locale}
          onPress={() => {
            setAppLocale(locale).catch(() => undefined);
          }}
          style={[styles.option, current === locale && styles.selected]}
        >
          <Text style={[styles.label, current === locale && styles.selectedLabel]}>
            {locale === 'en' ? t('language.english') : t('language.french')}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    alignSelf: 'flex-end',
    flexDirection: 'row',
    gap: space.space1,
    marginBottom: space.space6,
  },
  option: {
    alignItems: 'center',
    borderColor: color.gray300,
    borderRadius: radius.button,
    borderWidth: 1,
    justifyContent: 'center',
    minHeight: minTouchTarget,
    paddingHorizontal: space.space3,
  },
  selected: {
    backgroundColor: color.primary700,
    borderColor: color.primary700,
  },
  label: {
    color: color.gray700,
    fontSize: typography.caption.fontSize,
    fontWeight: typography.caption.fontWeight,
  },
  selectedLabel: {
    color: color.white,
  },
});
