/**
 * The gallery is the chunk's screenshot surface, so what it renders *is* the
 * evidence. These tests hold it to that: every section present, every string
 * translated in both locales, and no English left behind when the language
 * changes.
 *
 * The French pass is not decoration. `design-system.md` §16 requires layout to
 * survive French expansion, and the way that requirement quietly fails is a
 * string somebody forgot to translate — which looks fine, because English
 * always fits.
 */

import React from 'react';
import { render, screen } from '@testing-library/react-native';

import { GALLERY_SECTIONS, GalleryScreen } from './GalleryScreen';
import { i18n, setAppLocale } from '../../i18n';
import statesEn from '../../i18n/locales/en/states.json';
import statesFr from '../../i18n/locales/fr/states.json';

describe('GalleryScreen', () => {
  beforeEach(async () => {
    await setAppLocale('en');
  });

  it('renders every section', async () => {
    await render(<GalleryScreen />);
    for (const section of GALLERY_SECTIONS) {
      expect(screen.getByTestId(`gallery-section-${section}`)).toBeTruthy();
    }
  });

  it('renders one section alone when asked, for a legible screenshot', async () => {
    // A full-page capture of this screen is unreadable at phone width, and an
    // unreadable screenshot is not evidence of anything.
    await render(<GalleryScreen only="usage" />);
    expect(screen.getByTestId('gallery-section-usage')).toBeTruthy();
    expect(screen.queryByTestId('gallery-section-states')).toBeNull();
    expect(screen.queryByTestId('gallery-title')).toBeNull();
  });

  it('shows all three usage readings, including the one nothing has reported', async () => {
    await render(<GalleryScreen only="usage" />);
    expect(screen.getByTestId('usage-healthy')).toBeTruthy();
    expect(screen.getByTestId('usage-stale')).toBeTruthy();
    expect(screen.getByTestId('usage-never')).toBeTruthy();
  });

  it('shows the four states as four visually distinct messages', async () => {
    await render(<GalleryScreen only="states" />);
    for (const id of ['state-pending', 'state-empty', 'state-blocked', 'state-error']) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
    expect(screen.getByTestId('state-partial')).toBeTruthy();
  });

  it('keeps a pill for every state family the schema separates', async () => {
    await render(<GalleryScreen only="status" />);
    for (const id of [
      'pill-payment',
      'pill-provisioning',
      'pill-installation',
      'pill-activation',
      'pill-network',
    ]) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
  });

  it('renders French copy, not English fallbacks, after switching language', async () => {
    await setAppLocale('fr');
    await render(<GalleryScreen only="states" />);

    expect(screen.getByTestId('state-pending-title').props.children).toBe(
      statesFr.pendingProvisioning.title,
    );
    expect(screen.getByTestId('state-pending-title').props.children).not.toBe(
      statesEn.pendingProvisioning.title,
    );
  });

  it('resolves every key the gallery asks for in both locales', async () => {
    // i18next silently returns the key itself when a string is missing, which
    // renders as "gallery.sectionUsage" on screen and passes any test that only
    // checks something was rendered.
    const keys = [
      'gallery.title',
      'gallery.subtitle',
      'gallery.sectionStatus',
      'gallery.sectionUsage',
      'gallery.sectionStates',
      'gallery.sectionBanners',
      'status.paymentPaid',
      'status.provisioningOutcomeUnknown',
      'status.installationNotInstalled',
      'status.activationSuspended',
      'status.networkDetached',
      'usage.dataLabel',
      'usage.callsLabel',
      'usage.staleExplanation',
      'usage.neverUpdatedExplanation',
      'pendingProvisioning.title',
      'pendingProvisioning.body',
      'empty.linesTitle',
      'empty.linesBody',
      'empty.linesAction',
      'unsupportedDevice.title',
      'unsupportedDevice.body',
      'unsupportedDevice.beforePaying',
      'error.title',
      'error.genericBody',
      'error.retry',
      'error.contactSupport',
      'partialFailure.noCharge',
      'outcomeUnknown.reassurance',
    ];

    for (const locale of ['en', 'fr'] as const) {
      await setAppLocale(locale);
      for (const key of keys) {
        const value = i18n.t(key, { ns: 'states' });
        expect({ locale, key, value }).toEqual({ locale, key, value: expect.any(String) });
        expect(value).not.toBe(key);
        expect(value.length).toBeGreaterThan(0);
      }
    }
  });

  it('has French copy that is genuinely translated, not copied English', async () => {
    // A "translation" file that duplicates English passes a key-parity check
    // and fails every French speaker.
    const identical = Object.entries(statesEn.status).filter(
      ([key, english]) => statesFr.status[key as keyof typeof statesFr.status] === english,
    );
    // "Actif"/"Active" and similar near-cognates would be legitimate; none of
    // these happen to be identical, so the whole family should differ.
    expect(identical.map(([key]) => key)).toEqual([]);
  });
});
