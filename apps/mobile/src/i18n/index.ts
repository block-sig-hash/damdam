import i18n from 'i18next';
import {initReactI18next} from 'react-i18next';

import authEn from './locales/en/auth.json';
import commonEn from './locales/en/common.json';
import consumerEn from './locales/en/consumer.json';
import esimEn from './locales/en/esim.json';
import homeEn from './locales/en/home.json';
import paymentsEn from './locales/en/payments.json';
import statesEn from './locales/en/states.json';
import authFr from './locales/fr/auth.json';
import commonFr from './locales/fr/common.json';
import consumerFr from './locales/fr/consumer.json';
import esimFr from './locales/fr/esim.json';
import homeFr from './locales/fr/home.json';
import paymentsFr from './locales/fr/payments.json';
import statesFr from './locales/fr/states.json';
import {
  AppLocale,
  getDeviceLocale,
  getSavedLocale,
  normalizeLocale,
  persistLocale,
} from './locale';

export const namespaces = ['common', 'auth', 'consumer', 'home', 'esim', 'payments', 'states'] as const;

i18n.use(initReactI18next).init({
  compatibilityJSON: 'v4',
  fallbackLng: 'en',
  lng: getDeviceLocale(),
  ns: [...namespaces],
  defaultNS: 'common',
  interpolation: {escapeValue: false},
  resources: {
    en: {
      common: commonEn,
      auth: authEn,
      consumer: consumerEn,
      home: homeEn,
      esim: esimEn,
      payments: paymentsEn,
      states: statesEn,
    },
    fr: {
      common: commonFr,
      auth: authFr,
      consumer: consumerFr,
      home: homeFr,
      esim: esimFr,
      payments: paymentsFr,
      states: statesFr,
    },
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

/**
 * Every API request must send this so the backend's api_message()/
 * request_locale() (apps/api/app/i18n/catalog.py) render error text in
 * the user's selected language, not always English -- i18n.language
 * reflects the live current locale (device default, or a saved
 * override applied via setAppLocale), independent of any single
 * request's own body fields.
 */
export function localeHeader(): {'Accept-Language': AppLocale} {
  return {'Accept-Language': normalizeLocale(i18n.language)};
}

export {i18n};
export type {AppLocale} from './locale';
