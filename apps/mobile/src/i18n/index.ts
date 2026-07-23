import i18n from 'i18next';
import {initReactI18next} from 'react-i18next';

import authEn from './locales/en/auth.json';
import commonEn from './locales/en/common.json';
import esimEn from './locales/en/esim.json';
import homeEn from './locales/en/home.json';
import paymentsEn from './locales/en/payments.json';
import safetyEn from './locales/en/safety.json';
import authFr from './locales/fr/auth.json';
import commonFr from './locales/fr/common.json';
import esimFr from './locales/fr/esim.json';
import homeFr from './locales/fr/home.json';
import paymentsFr from './locales/fr/payments.json';
import safetyFr from './locales/fr/safety.json';
import {
  AppLocale,
  getDeviceLocale,
  getSavedLocale,
  persistLocale,
} from './locale';

export const namespaces = ['common', 'auth', 'home', 'esim', 'safety', 'payments'] as const;

i18n.use(initReactI18next).init({
  compatibilityJSON: 'v4',
  fallbackLng: 'en',
  lng: getDeviceLocale(),
  ns: [...namespaces],
  defaultNS: 'common',
  interpolation: {escapeValue: false},
  resources: {
    en: {common: commonEn, auth: authEn, home: homeEn, esim: esimEn, safety: safetyEn, payments: paymentsEn},
    fr: {common: commonFr, auth: authFr, home: homeFr, esim: esimFr, safety: safetyFr, payments: paymentsFr},
  },
  returnNull: false,
}).catch(() => undefined);

getSavedLocale().then(saved => {
  if (saved) {
    return i18n.changeLanguage(saved);
  }
  return undefined;
}).catch(() => undefined);

export async function setAppLocale(locale: AppLocale): Promise<void> {
  await persistLocale(locale);
  await i18n.changeLanguage(locale);
}

export {i18n};
export type {AppLocale} from './locale';
