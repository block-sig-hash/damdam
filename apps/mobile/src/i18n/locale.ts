import AsyncStorage from '@react-native-async-storage/async-storage';
import {findBestLanguageTag, getLocales} from 'react-native-localize';

export const SUPPORTED_LOCALES = ['en', 'fr'] as const;
export type AppLocale = (typeof SUPPORTED_LOCALES)[number];

const STORAGE_KEY = 'damdam.locale';

export function normalizeLocale(value: string | null | undefined): AppLocale {
  return value?.toLowerCase().startsWith('fr') ? 'fr' : 'en';
}

export function getDeviceLocale(): AppLocale {
  const best = findBestLanguageTag([...SUPPORTED_LOCALES]);
  return best ? normalizeLocale(best.languageTag) : normalizeLocale(getLocales()[0]?.languageTag);
}

export async function getSavedLocale(): Promise<AppLocale | null> {
  const saved = await AsyncStorage.getItem(STORAGE_KEY);
  return saved === 'en' || saved === 'fr' ? saved : null;
}

export async function persistLocale(locale: AppLocale): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, locale);
}
