import {i18n, setAppLocale} from './index';

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
});
