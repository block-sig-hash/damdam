import React from 'react';
import {
  cleanup,
  render,
  screen,
  waitFor,
} from '@testing-library/react-native';
import { SignInScreen } from './SignInScreen';
import { ApiError } from '../../api/http';
import * as identityClient from '../../api/identityClient';
import { setAppLocale } from '../../i18n';
import { press, type } from '../../testing/interact';

/**
 * US-37 AC-37.2 — email sign-in, which is also signup.
 *
 * The property this file protects hardest is a *negative* one: the screen must
 * not reveal whether an address already has an account. The server answers
 * identically for both (AC-29, no pre-verification enumeration), and a client
 * that drew "welcome back" from the request step would reintroduce the oracle
 * the server refuses to provide.
 */

jest.mock('../../api/identityClient');

const mockedRequest = identityClient.requestEmailLogin as jest.Mock;
const mockedConfirm = identityClient.confirmEmailLogin as jest.Mock;

function authResponse(isNew: boolean) {
  return {
    access_token: 'access-1',
    refresh_token: 'refresh-1',
    is_new_user: isNew,
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
}

async function renderScreen(overrides: Partial<React.ComponentProps<typeof SignInScreen>> = {}) {
  const onAuthenticated = jest.fn();
  const onRecover = jest.fn();
  await render(
    <SignInScreen
      onAuthenticated={onAuthenticated}
      onRecover={onRecover}
      {...overrides}
    />,
  );
  return { onAuthenticated, onRecover };
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedRequest.mockResolvedValue({ message: 'sent' });
});

afterEach(async () => {
  await cleanup();
  await setAppLocale('en');
});

it('sends the same "check your email" screen whether or not the address is known', async () => {
  await renderScreen();

  await type('sign-in-email-input', 'stranger@example.test');
  await press('sign-in-submit');

  await waitFor(() => expect(screen.getByTestId('sign-in-sent')).toBeTruthy());
  // Nothing on this screen distinguishes a registered address from an unknown
  // one. It cannot: the request that produced it does not know either.
  expect(screen.getByTestId('sign-in-sent-body').props.children).toContain(
    'stranger@example.test',
  );
});

it('normalizes the address before sending it', async () => {
  await renderScreen();

  await type('sign-in-email-input', '  Me@Example.TEST ');
  await press('sign-in-submit');

  // The server stores identifiers normalized, and the unique index compares
  // normalized values. Sending the typed form would let one person hold two
  // "different" claims on one mailbox.
  await waitFor(() =>
    expect(mockedRequest).toHaveBeenCalledWith('me@example.test', 'en'),
  );
});

it('refuses to send to something that is not an address, without calling the server', async () => {
  await renderScreen();

  await type('sign-in-email-input', 'not-an-email');
  await press('sign-in-submit');

  await waitFor(() => expect(screen.getByTestId('sign-in-error')).toBeTruthy());
  expect(mockedRequest).not.toHaveBeenCalled();
});

it('hands the session over once mailbox control is proved', async () => {
  mockedConfirm.mockResolvedValue(authResponse(true));
  const { onAuthenticated } = await renderScreen();

  await type('sign-in-email-input', 'me@example.test');
  await press('sign-in-submit');
  await waitFor(() => expect(screen.getByTestId('sign-in-sent')).toBeTruthy());

  await type('sign-in-code-input', 'token-abc');
  await press('sign-in-code-submit');

  await waitFor(() =>
    expect(onAuthenticated).toHaveBeenCalledWith(
      expect.objectContaining({ access_token: 'access-1' }),
      'me@example.test',
    ),
  );
});

it('keeps the address on screen when a link has expired', async () => {
  // Sending the customer back to retype an address they got right is the
  // fastest way to make an expired link feel like a rejection.
  mockedConfirm.mockRejectedValue(
    new ApiError('identity_token_expired', 'expired', 410),
  );
  await renderScreen();

  await type('sign-in-email-input', 'me@example.test');
  await press('sign-in-submit');
  await waitFor(() => expect(screen.getByTestId('sign-in-sent')).toBeTruthy());

  await type('sign-in-code-input', 'stale-token');
  await press('sign-in-code-submit');

  await waitFor(() => expect(screen.getByTestId('sign-in-error')).toBeTruthy());
  expect(screen.getByTestId('sign-in-error').props.children).toBeTruthy();
  // Still on the "check your email" step, with a resend button.
  expect(screen.getByTestId('sign-in-resend')).toBeTruthy();
});

it('does not confirm an empty code', async () => {
  await renderScreen();

  await type('sign-in-email-input', 'me@example.test');
  await press('sign-in-submit');
  await waitFor(() => expect(screen.getByTestId('sign-in-sent')).toBeTruthy());

  await press('sign-in-code-submit');

  expect(mockedConfirm).not.toHaveBeenCalled();
});

it('explains why sign-in was asked for when a deep link brought the customer here', async () => {
  await renderScreen({ contextMessage: 'Sign in to continue to your invitation' });

  expect(screen.getByTestId('sign-in-context')).toBeTruthy();
});

it('offers the retained phone sign-in journey to legacy accounts', async () => {
  const onUsePhone = jest.fn();
  await renderScreen({ onUsePhone });

  await press('sign-in-use-phone');

  expect(onUsePhone).toHaveBeenCalledTimes(1);
});

it('renders in French', async () => {
  await setAppLocale('fr');
  await renderScreen();

  expect(screen.getByText('Connectez-vous ou créez un compte')).toBeTruthy();
  // The locale travels with the request so the mail is composed in the
  // language the customer is reading the app in.
  await type('sign-in-email-input', 'me@example.test');
  await press('sign-in-submit');
  await waitFor(() =>
    expect(mockedRequest).toHaveBeenCalledWith('me@example.test', 'fr'),
  );
});
