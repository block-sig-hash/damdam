import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react-native';
import { CliApiError, captureCliConsent, type VerifiedCallerIdentity } from '../../api/cliClient';
import { CliConsentScreen } from './CliConsentScreen';
import { CLI_CONSENT_VERSION } from './useCliConsent';

jest.mock('../../api/cliClient', () => {
  const actual = jest.requireActual('../../api/cliClient');
  return { ...actual, captureCliConsent: jest.fn() };
});

afterEach(async () => cleanup());

const mockCapture = captureCliConsent as jest.MockedFunction<typeof captureCliConsent>;

const ACTIVE: VerifiedCallerIdentity = {
  id: 'identity-1',
  phone_number: '+2348031234567',
  status: 'active',
  phone_verification_status: 'verified',
  consent_version: CLI_CONSENT_VERSION,
  consent_at: '2026-07-25T00:00:00Z',
  created_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:00:00Z',
};

beforeEach(() => {
  mockCapture.mockReset();
});

describe('CliConsentScreen', () => {
  it('AC-14.11: captures consent and activates', async () => {
    mockCapture.mockResolvedValue(ACTIVE);
    const onConsented = jest.fn();
    await render(
      <CliConsentScreen
        accessToken="token"
        identityId="identity-1"
        phoneNumber="+2348031234567"
        onConsented={onConsented}
      />,
    );

    await fireEvent.press(screen.getByTestId('cli-consent-submit'));

    expect(mockCapture).toHaveBeenCalledWith('token', 'identity-1', CLI_CONSENT_VERSION);
    expect(onConsented).toHaveBeenCalledWith(ACTIVE);
  });

  it('shows an inline error on failure', async () => {
    mockCapture.mockRejectedValue(
      new CliApiError('number_already_verified_elsewhere', 'Already verified elsewhere.'),
    );
    await render(
      <CliConsentScreen
        accessToken="token"
        identityId="identity-1"
        phoneNumber="+2348031234567"
        onConsented={jest.fn()}
      />,
    );

    await fireEvent.press(screen.getByTestId('cli-consent-submit'));

    expect(screen.getByTestId('cli-consent-error')).toBeTruthy();
    expect(
      screen.getByText('This number is already verified on another account.'),
    ).toBeTruthy();
  });
});
