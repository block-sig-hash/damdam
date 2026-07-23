import React from 'react';
import {cleanup, render} from '@testing-library/react-native';
import {PhoneEntryScreen} from '../screens/PhoneEntry/PhoneEntryScreen';
import {SosConfirmScreen} from '../screens/SosConfirm/SosConfirmScreen';
import {EsimActivationGuideScreen} from '../screens/EsimActivation/EsimActivationGuideScreen';
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

  it('renders French safety copy and accessibility text', async () => {
    const sos = await render(<SosConfirmScreen onConfirmed={jest.fn()} />);
    expect(sos.getByText("SOS d'urgence")).toBeTruthy();
    expect(sos.getByLabelText('SOS / Urgence')).toBeTruthy();
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
});
