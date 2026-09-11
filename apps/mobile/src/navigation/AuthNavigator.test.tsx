import React from 'react';
import { cleanup, render, screen } from '@testing-library/react-native';
import { setAppLocale } from '../i18n';
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
}));

const mockedLoadPending = deepLinks.loadPendingLink as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockedLoadPending.mockResolvedValue(null);
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
