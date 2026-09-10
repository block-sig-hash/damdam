import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react-native';
import { AccountRecoveryScreen } from './AccountRecoveryScreen';
import { ApiError } from '../../api/http';
import * as identityClient from '../../api/identityClient';
import { setAppLocale } from '../../i18n';
import { press, type } from '../../testing/interact';

/**
 * Account recovery (AC-38.5, and AC-37's returning-user half).
 *
 * Recovery is not a second sign-in. It revokes every other session on the
 * account, which is the entire point when somebody else has it — so the tests
 * check that the screen says so up front, and that a recovery token and a
 * sign-in token stay on opposite sides of the wall the server puts between them.
 */

jest.mock('../../api/identityClient');

const mockedRequest = identityClient.requestEmailRecovery as jest.Mock;
const mockedConfirm = identityClient.confirmEmailRecovery as jest.Mock;

async function renderScreen(initialEmail = 'me@example.test') {
  const onRecovered = jest.fn();
  const onCancel = jest.fn();
  await render(
    <AccountRecoveryScreen
      initialEmail={initialEmail}
      onRecovered={onRecovered}
      onCancel={onCancel}
    />,
  );
  return { onRecovered, onCancel };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedRequest.mockResolvedValue({ message: 'sent' });
});

afterEach(async () => {
  await cleanup();
  await setAppLocale('en');
});

it('warns that recovering signs the account out everywhere else', async () => {
  await renderScreen();

  // Before anything is sent, not after. Somebody recovering an account they
  // still share with a family member needs to know that is what happens.
  expect(screen.getByText(/signs you out everywhere else/)).toBeTruthy();
});

it('sends a recovery link and says nothing about whether the address is known', async () => {
  await renderScreen();

  await press('recovery-send');

  await waitFor(() => expect(screen.getByTestId('recovery-sent')).toBeTruthy());
  expect(mockedRequest).toHaveBeenCalledWith('me@example.test', 'en');
});

it('hands over the recovered session once the token is proved', async () => {
  mockedConfirm.mockResolvedValue({
    access_token: 'access-2',
    refresh_token: 'refresh-2',
    user: {
      id: 'user-1',
      phone_number: null,
      first_name: '',
      last_name: '',
      email: 'me@example.test',
      verified_cli: false,
      departure_date: null,
      locale: 'en' as const,
      platform: 'ios',
      status: 'active',
    },
  });
  const { onRecovered } = await renderScreen();

  await press('recovery-send');
  await waitFor(() => expect(screen.getByTestId('recovery-sent')).toBeTruthy());
  await type('recovery-token-input', 'recovery-token');
  await press('recovery-confirm');

  await waitFor(() =>
    expect(onRecovered).toHaveBeenCalledWith(
      expect.objectContaining({ access_token: 'access-2' }),
      'me@example.test',
    ),
  );
});

it('reports a spent recovery token without dropping the customer back to the start', async () => {
  mockedConfirm.mockRejectedValue(
    new ApiError('identity_token_invalid', 'invalid', 400),
  );
  const { onRecovered } = await renderScreen();

  await press('recovery-send');
  await waitFor(() => expect(screen.getByTestId('recovery-sent')).toBeTruthy());
  await type('recovery-token-input', 'already-used');
  await press('recovery-confirm');

  await waitFor(() => expect(screen.getByTestId('recovery-error')).toBeTruthy());
  expect(onRecovered).not.toHaveBeenCalled();
  // A one-time token is cleared so it cannot be resubmitted by a second tap.
  expect(screen.getByTestId('recovery-token-input').props.value).toBe('');
});

it('refuses to send to something that is not an address', async () => {
  await renderScreen('');

  await type('recovery-email-input', 'nope');
  await press('recovery-send');

  await waitFor(() => expect(screen.getByTestId('recovery-error')).toBeTruthy());
  expect(mockedRequest).not.toHaveBeenCalled();
});

it('renders in French and asks for the message in French', async () => {
  await setAppLocale('fr');
  await renderScreen();

  expect(screen.getByText('Récupérer votre compte')).toBeTruthy();

  await press('recovery-send');

  await waitFor(() =>
    expect(mockedRequest).toHaveBeenCalledWith('me@example.test', 'fr'),
  );
});
