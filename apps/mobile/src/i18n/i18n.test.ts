import {i18n, setAppLocale} from './index';
import authEn from './locales/en/auth.json';
import authFr from './locales/fr/auth.json';
import commonEn from './locales/en/common.json';
import commonFr from './locales/fr/common.json';
import esimEn from './locales/en/esim.json';
import esimFr from './locales/fr/esim.json';
import homeEn from './locales/en/home.json';
import homeFr from './locales/fr/home.json';
import paymentsEn from './locales/en/payments.json';
import paymentsFr from './locales/fr/payments.json';
import safetyEn from './locales/en/safety.json';
import safetyFr from './locales/fr/safety.json';

function keys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object') return [prefix];
  return Object.entries(value).flatMap(([key, nested]) =>
    keys(nested, prefix ? `${prefix}.${key}` : key),
  );
}

describe('mobile locale runtime', () => {
  afterEach(async () => {
    await setAppLocale('en');
  });

  it('renders bundled French copy after a runtime language switch', async () => {
    expect(i18n.t('actions.continue', {ns: 'common'})).toBe('Continue');

    await setAppLocale('fr');

    expect(i18n.t('actions.continue', {ns: 'common'})).toBe('Continuer');
    expect(i18n.t('language.label', {ns: 'common'})).toBe('Langue');
  });

  it('keeps every French namespace structurally aligned with English', () => {
    for (const [english, french] of [
      [commonEn, commonFr],
      [authEn, authFr],
      [homeEn, homeFr],
      [esimEn, esimFr],
      [safetyEn, safetyFr],
      [paymentsEn, paymentsFr],
    ]) {
      expect(keys(french).sort()).toEqual(keys(english).sort());
    }
  });
});
