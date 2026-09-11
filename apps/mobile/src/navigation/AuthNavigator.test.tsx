import React from 'react';
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
} from '@testing-library/react-native';
import { setAppLocale } from '../i18n';
import * as identityClient from '../api/identityClient';
import * as deepLinks from '../services/deepLinks';
import { press } from '../testing/interact';
import { AuthNavigator } from './AuthNavigator';

jest.mock('../api/identityClient');
jest.mock('../api/authClient', () => ({
  ...jest.requireActual('../api/authClient'),
  requestOtp: jest.fn(),
}));
jest.mock('../services/deepLinks', () => ({
  ...jest.requireActual('../services/deepLinks'),
  loadPendingLink: jest.fn(),
  clearPendingLink: jest.fn(),
  subscribeToDeepLinks: jest.fn(),
}));

const mockedLoadPending = deepLinks.loadPendingLink as jest.Mock;
const mockedClearPending = deepLinks.clearPendingLink as jest.Mock;
const mockedConfirmLogin = identityClient.confirmEmailLogin as jest.Mock;
const mockedConfirmRecovery = identityClient.confirmEmailRecovery as jest.Mock;
const mockedSubscribe = deepLinks.subscribeToDeepLinks as jest.Mock;

const SESSION = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  is_new_user: false,
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
};

beforeEach(() => {
  jest.clearAllMocks();
  mockedLoadPending.mockResolvedValue(null);
  mockedClearPending.mockResolvedValue(undefined);
  mockedSubscribe.mockReturnValue(() => undefined);
});

it('handles an invitation that arrives while the signed-out app is warm', async () => {
  await render(<AuthNavigator onAuthenticated={jest.fn()} />);
  const onLink = mockedSubscribe.mock.calls[0][0] as (
    link: deepLinks.PendingLink,
  ) => void;

  await act(async () => {
    onLink({ kind: 'invitation', token: 'warm-invitation' });
  });

  await waitFor(() => expect(screen.getByTestId('sign-in-context')).toBeTruthy());
});

it('consumes a cold email login link and hands off the authenticated session', async () => {
  mockedLoadPending.mockResolvedValue({
    kind: 'email-login',
    token: 'login-token',
  });
  mockedConfirmLogin.mockResolvedValue(SESSION);
  const onAuthenticated = jest.fn();

  await render(<AuthNavigator onAuthenticated={onAuthenticated} />);

  await waitFor(() =>
    expect(mockedConfirmLogin).toHaveBeenCalledWith('login-token'),
  );
  await waitFor(() =>
    expect(onAuthenticated).toHaveBeenCalledWith(
      expect.objectContaining({ accessToken: 'access-1' }),
    ),
  );
  expect(mockedConfirmRecovery).not.toHaveBeenCalled();
  expect(mockedClearPending).toHaveBeenCalled();
});

it('uses the revoking recovery endpoint for a recovery link', async () => {
  mockedLoadPending.mockResolvedValue({
    kind: 'email-recovery',
    token: 'recovery-token',
  });
  mockedConfirmRecovery.mockResolvedValue(SESSION);
  const onAuthenticated = jest.fn();

  await render(<AuthNavigator onAuthenticated={onAuthenticated} />);

  await waitFor(() =>
    expect(mockedConfirmRecovery).toHaveBeenCalledWith('recovery-token'),
  );
  await waitFor(() => expect(onAuthenticated).toHaveBeenCalled());
  expect(mockedConfirmLogin).not.toHaveBeenCalled();
});

afterEach(async () => {
  await cleanup();
  await setAppLocale('en');
});

it('keeps the legacy phone account journey reachable from production sign-in', async () => {
  await render(<AuthNavigator onAuthenticated={jest.fn()} />);

  await press('sign-in-use-phone');
  expect(screen.getByTestId('phone-entry-input')).toBeTruthy();

  await press('phone-entry-cancel');
  expect(screen.getByTestId('sign-in-email-input')).toBeTruthy();
});
