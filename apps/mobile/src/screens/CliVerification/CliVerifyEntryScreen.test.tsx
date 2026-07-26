import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react-native';
import { CliApiError, startCliVerification, type VerifiedCallerIdentity } from '../../api/cliClient';
import { CliVerifyEntryScreen } from './CliVerifyEntryScreen';

jest.mock('../../api/cliClient', () => {
  const actual = jest.requireActual('../../api/cliClient');
  return { ...actual, startCliVerification: jest.fn() };
});

afterEach(async () => cleanup());

const mockStart = startCliVerification as jest.MockedFunction<typeof startCliVerification>;

const IDENTITY: VerifiedCallerIdentity = {
  id: 'identity-1',
  phone_number: '+2348031234567',
  status: 'phone_verification_pending',
  phone_verification_status: 'pending',
  consent_version: null,
  consent_at: null,
  created_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:00:00Z',
};

beforeEach(() => {
  mockStart.mockReset();
});

describe('CliVerifyEntryScreen', () => {
  it('AC-14.1/AC-14.10: disables Send code until a valid Nigerian number is entered', async () => {
    await render(
      <CliVerifyEntryScreen accessToken="token" onStarted={jest.fn()} onCancel={jest.fn()} />,
    );

    expect(screen.getByTestId('cli-verify-entry-submit').props.accessibilityState.disabled).toBe(
      true,
    );

    await fireEvent.changeText(screen.getByTestId('cli-verify-entry-input'), '08031234567');

    expect(screen.getByTestId('cli-verify-entry-submit').props.accessibilityState.disabled).toBe(
      false,
    );
  });

  it('starts verification and calls onStarted', async () => {
    mockStart.mockResolvedValue(IDENTITY);
    const onStarted = jest.fn();
    await render(
      <CliVerifyEntryScreen accessToken="token" onStarted={onStarted} onCancel={jest.fn()} />,
    );

    await fireEvent.changeText(screen.getByTestId('cli-verify-entry-input'), '08031234567');
    await fireEvent.press(screen.getByTestId('cli-verify-entry-submit'));

    expect(mockStart).toHaveBeenCalledWith('token', '08031234567');
    expect(onStarted).toHaveBeenCalledWith(IDENTITY);
  });

  it('shows an inline error on failure', async () => {
    mockStart.mockRejectedValue(new CliApiError('invalid_phone_number', 'Enter a valid number.'));
    await render(
      <CliVerifyEntryScreen accessToken="token" onStarted={jest.fn()} onCancel={jest.fn()} />,
    );

    await fireEvent.changeText(screen.getByTestId('cli-verify-entry-input'), '08031234567');
    await fireEvent.press(screen.getByTestId('cli-verify-entry-submit'));

    expect(screen.getByTestId('cli-verify-entry-error')).toBeTruthy();
    expect(screen.getByText('Enter a valid Nigerian mobile number.')).toBeTruthy();
  });

  it('calls onCancel from the "Not now" link', async () => {
    const onCancel = jest.fn();
    await render(
      <CliVerifyEntryScreen accessToken="token" onStarted={jest.fn()} onCancel={onCancel} />,
    );

    await fireEvent.press(screen.getByTestId('cli-verify-entry-cancel'));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
