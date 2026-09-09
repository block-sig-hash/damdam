import React from 'react';
import {cleanup, render} from '@testing-library/react-native';
import {PhoneEntryScreen} from '../screens/PhoneEntry/PhoneEntryScreen';
import {EsimActivationGuideScreen} from '../screens/EsimActivation/EsimActivationGuideScreen';
import {CliVerifyEntryScreen} from '../screens/CliVerification/CliVerifyEntryScreen';
import {i18n} from './index';

describe('French mobile rendering', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('fr');
  });

  afterEach(async () => {
    await cleanup();
    await i18n.changeLanguage('en');
  });

  it('renders French auth copy in a real component', async () => {
    const phone = await render(
      <PhoneEntryScreen onOtpSent={jest.fn()} onAccountExists={jest.fn()} />,
    );
    expect(phone.getByText('Quel est votre numéro de téléphone ?')).toBeTruthy();
  });

  it('renders French eSIM guide instructions', async () => {
    const guide = await render(
      <EsimActivationGuideScreen
        platform="ios"
        deviceModel="iPhone 14"
        onShowQrCode={jest.fn()}
        onConfirmActivated={jest.fn()}
      />,
    );
    expect(guide.getByText('Activez votre eSIM')).toBeTruthy();
    expect(guide.getByText('Ouvrez Réglages, puis Données cellulaires.')).toBeTruthy();
  });

  it('renders French caller ID copy and accessibility text', async () => {
    const callerId = await render(
      <CliVerifyEntryScreen
        accessToken="access-token"
        onStarted={jest.fn()}
        onCancel={jest.fn()}
      />,
    );
    expect(callerId.getByText("Vérifiez votre identité d'appelant")).toBeTruthy();
    expect(callerId.getByLabelText('Numéro mobile nigérian')).toBeTruthy();
    expect(callerId.getByText('Envoyer le code')).toBeTruthy();
  });
});
