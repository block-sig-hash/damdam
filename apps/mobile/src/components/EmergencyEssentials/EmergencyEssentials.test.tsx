import React from 'react';
import { Linking, StyleSheet } from 'react-native';
import { fireEvent, render, waitFor } from '@testing-library/react-native';
import { getEmergencyContact } from '../../api/emergencyContactClient';
import { EMERGENCY_PHRASES } from '../../content/emergencyEssentials';
import { EmergencyEssentials } from './EmergencyEssentials';
import {i18n} from '../../i18n';

jest.mock('../../api/emergencyContactClient', () => ({
  getEmergencyContact: jest.fn(),
}));

const mockGetContact = getEmergencyContact as jest.MockedFunction<typeof getEmergencyContact>;

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
});

it('AC-12.2: shows the HTO operator contact when one is assigned', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: 'Kano Pilgrims Welfare HTO',
    hto_operator_phone_number: '+2348012345678',
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);

  expect(await view.findByTestId('emergency-hto-contact')).toBeTruthy();
  expect(view.getByText('Kano Pilgrims Welfare HTO')).toBeTruthy();
  expect(view.getByText('+2348012345678')).toBeTruthy();
});

it('hides the HTO row for a direct/retail pilgrim with no assigned HTO', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: null,
    hto_operator_phone_number: null,
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);

  await waitFor(() => expect(mockGetContact).toHaveBeenCalled());
  expect(view.queryByTestId('emergency-hto-contact')).toBeNull();
});

it('AC-12.2: always shows the DamDam support WhatsApp row', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: null,
    hto_operator_phone_number: null,
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);

  expect(await view.findByTestId('emergency-support-contact')).toBeTruthy();
});

it('AC-12.2: renders all five key phrases in English and Arabic', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: null,
    hto_operator_phone_number: null,
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);
  await view.findByTestId('emergency-support-contact');

  for (const phrase of EMERGENCY_PHRASES) {
    const row = view.getByTestId(`emergency-phrase-${phrase.key}`);
    expect(row).toBeTruthy();
    expect(view.getByText(i18n.t(`phrases.${phrase.key}`, {ns: 'safety'}))).toBeTruthy();
    expect(view.getByText(phrase.arabic)).toBeTruthy();
  }
});

it('renders Arabic phrase text right-to-left', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: null,
    hto_operator_phone_number: null,
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);
  await view.findByTestId('emergency-support-contact');

  const arabicText = view.getByText(EMERGENCY_PHRASES[0].arabic);
  expect(StyleSheet.flatten(arabicText.props.style)).toMatchObject({
    textAlign: 'right',
    writingDirection: 'rtl',
  });
});

it('tapping the HTO row opens the phone dialer', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: 'Kano Pilgrims Welfare HTO',
    hto_operator_phone_number: '+2348012345678',
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);
  fireEvent.press(await view.findByTestId('emergency-hto-contact'));

  expect(Linking.openURL).toHaveBeenCalledWith('tel:+2348012345678');
});

it('tapping the support row opens WhatsApp', async () => {
  mockGetContact.mockResolvedValue({
    hto_operator_name: null,
    hto_operator_phone_number: null,
  });

  const view = await render(<EmergencyEssentials accessToken="token" />);
  fireEvent.press(await view.findByTestId('emergency-support-contact'));

  expect(Linking.openURL).toHaveBeenCalledWith(
    expect.stringContaining('https://wa.me/'),
  );
});
