/**
 * The Calls states (`VOICE-EXPANSION.md`, chunk 08 row).
 *
 * Two of these tests are about what chunk 08 must *not* do. Design work on a
 * feature nobody has built yet is exactly where a permission or an SDK sneaks
 * into the manifest "ready for later", and chunk 04's retirement guard exists
 * because that had already happened once.
 */

import { readFileSync } from 'fs';
import { join } from 'path';

import React from 'react';
import { render, screen } from '@testing-library/react-native';

import { CallSetupCard, KeypadPreview } from './CallSetupCard';
import { setAppLocale } from '../../i18n';
import statesEn from '../../i18n/locales/en/states.json';
import statesFr from '../../i18n/locales/fr/states.json';

beforeEach(async () => {
  await setAppLocale('en');
});

describe('CallSetupCard', () => {
  it('says which of the two modes is about to happen', async () => {
    // They bill, route and fail differently. Someone who thinks they are making
    // one while making the other gets a surprise on a bill, or a call that will
    // not connect with no internet.
    await render(
      <CallSetupCard
        mode="carrier"
        outboundIdentity="+234 801 234 5678"
        payer={{ kind: 'personal' }}
        destination="Nigeria mobile"
        ratePerMinute="₦12"
        currency="NGN"
        testID="call"
      />,
    );
    expect(screen.getByTestId('call-mode').props.accessibilityLabel).toBe(
      `${statesEn.calls.modeLabel}: ${statesEn.calls.modeCarrierTitle}`,
    );
    expect(screen.getByTestId('call-mode-body').props.children).toBe(
      statesEn.calls.modeCarrierBody,
    );
  });

  it('tells a work caller what their employer can and cannot see', async () => {
    // Before they dial, not after. The distinction between "that it happened"
    // and "what was said" is the whole point of stating it.
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity="+44 20 7946 0000"
        payer={{ kind: 'work', organization: 'Acme Ltd' }}
        destination="United Kingdom mobile"
        ratePerMinute="£0.03"
        currency="GBP"
        testID="call"
      />,
    );
    const payer = screen.getByTestId('call-payer').props.accessibilityLabel;
    expect(payer).toContain('Acme Ltd');
    expect(payer).toContain('not what was said');
  });

  it('says a personal call is not visible to the organization', async () => {
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity="+234 801 234 5678"
        payer={{ kind: 'personal' }}
        destination="Nigeria mobile"
        ratePerMinute="₦12"
        currency="NGN"
        testID="call"
      />,
    );
    expect(screen.getByTestId('call-payer').props.accessibilityLabel).toContain(
      'Your organization cannot see it',
    );
  });

  it('admits when it cannot confirm the number the other party will see', async () => {
    // Guessing an outbound identity is worse than saying we do not know: the
    // network decides, and a wrong promise here is a wrong promise about who
    // the recipient thinks is calling.
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity={null}
        payer={{ kind: 'personal' }}
        destination="United Kingdom mobile"
        ratePerMinute="£0.03"
        currency="GBP"
        testID="call"
      />,
    );
    const identity = screen.getByTestId('call-identity').props.accessibilityLabel;
    expect(identity).toContain(statesEn.calls.identityUnknown);
    expect(identity).toContain('We will not guess');
  });

  it('refuses to offer a call it cannot price', async () => {
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity="+234 801 234 5678"
        payer={{ kind: 'personal' }}
        destination="Somewhere unpriced"
        ratePerMinute={null}
        currency="NGN"
        onCall={() => undefined}
        testID="call"
      />,
    );
    expect(screen.getByTestId('call-action').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByTestId('call-rate').props.accessibilityLabel).toContain(
      'We will not place a call we cannot price',
    );
  });

  it('treats an empty formatted rate as unpriced', async () => {
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity="+234 801 234 5678"
        payer={{ kind: 'personal' }}
        destination="Unknown destination"
        ratePerMinute="   "
        currency="NGN"
        onCall={() => undefined}
        testID="call"
      />,
    );
    expect(screen.getByTestId('call-action').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByTestId('call-rate').props.accessibilityLabel).toContain(
      'We will not place a call we cannot price',
    );
  });

  it('marks the rate as an estimate rather than a price', async () => {
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity="+234 801 234 5678"
        payer={{ kind: 'personal' }}
        destination="Nigeria mobile"
        ratePerMinute="₦12"
        currency="NGN"
        testID="call"
      />,
    );
    expect(screen.getByTestId('call-rate').props.accessibilityLabel).toContain('An estimate');
  });

  it('labels the carrier action as opening the phone dialler, not calling in-app', async () => {
    await render(
      <CallSetupCard
        mode="carrier"
        outboundIdentity="+234 801 234 5678"
        payer={{ kind: 'personal' }}
        destination="Nigeria mobile"
        ratePerMinute="₦12"
        currency="NGN"
        onCall={() => undefined}
        testID="call"
      />,
    );
    expect(screen.getByText(statesEn.calls.openDialler)).toBeTruthy();
  });

  it('renders in French without falling back to English', async () => {
    await setAppLocale('fr');
    await render(
      <CallSetupCard
        mode="internet"
        outboundIdentity={null}
        payer={{ kind: 'work', organization: 'Acme SARL' }}
        destination="Royaume-Uni mobile"
        ratePerMinute={null}
        currency="EUR"
        testID="call"
      />,
    );
    expect(screen.getByTestId('call-mode-body').props.children).toBe(
      statesFr.calls.modeInternetBody,
    );
  });
});

describe('KeypadPreview', () => {
  it('gives every key a spoken label, not a bare glyph', async () => {
    // In-call menu navigation is precisely when somebody is listening rather
    // than looking.
    await render(<KeypadPreview testID="keypad" />);
    for (const digit of ['1', '9', '*', '0', '#']) {
      expect(screen.getByTestId(`keypad-${digit}`).props.accessibilityLabel).toBe(
        `Dial ${digit}`,
      );
    }
  });

  it('explains what the keypad is for', async () => {
    await render(<KeypadPreview testID="keypad" />);
    expect(screen.getByText(statesEn.calls.keypadHelp)).toBeTruthy();
  });
});

describe('what this chunk deliberately does not add', () => {
  const MOBILE_ROOT = join(__dirname, '..', '..', '..');

  it('requests no microphone permission', () => {
    // Chunk 04's guard asserts RECORD_AUDIO is absent, and this chunk designs
    // the calling states without shipping the capability. Adding the permission
    // "ready for V04" would request something the product does not yet use.
    const manifest = readFileSync(
      join(MOBILE_ROOT, 'android', 'app', 'src', 'main', 'AndroidManifest.xml'),
      'utf8',
    );
    expect(manifest).not.toContain('RECORD_AUDIO');

    const plist = readFileSync(join(MOBILE_ROOT, 'ios', 'DamDam', 'Info.plist'), 'utf8');
    expect(plist).not.toContain('NSMicrophoneUsageDescription');
  });

  it('ships no call client or voice SDK', () => {
    const packageJson = JSON.parse(
      readFileSync(join(MOBILE_ROOT, 'package.json'), 'utf8'),
    ) as { dependencies?: Record<string, string>; devDependencies?: Record<string, string> };
    const all = { ...packageJson.dependencies, ...packageJson.devDependencies };
    for (const forbidden of Object.keys(all)) {
      expect(forbidden).not.toMatch(/telnyx|webrtc|callkit|voip/i);
    }
  });

  it('still explains the carrier alternative when the microphone is refused', () => {
    // Otherwise a denied permission reads as "no calls", when in fact the
    // carrier route needs no microphone at all.
    expect(statesEn.calls.micDeniedAlternative).toMatch(/carrier call/i);
    expect(statesFr.calls.micDeniedAlternative).toMatch(/opérateur/i);
  });
});
