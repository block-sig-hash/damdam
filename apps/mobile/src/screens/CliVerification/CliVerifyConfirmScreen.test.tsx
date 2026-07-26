import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react-native';
import {
  CliApiError,
  confirmCliVerification,
  type VerifiedCallerIdentity,
} from '../../api/cliClient';
import { CliVerifyConfirmScreen } from './CliVerifyConfirmScreen';

jest.mock('../../api/cliClient', () => {
  const actual = jest.requireActual('../../api/cliClient');
  return { ...actual, confirmCliVerification: jest.fn() };
});

afterEach(async () => cleanup());

const mockConfirm = confirmCliVerification as jest.MockedFunction<typeof confirmCliVerification>;

const CONFIRMED: VerifiedCallerIdentity = {
  id: 'identity-1',
  phone_number: '+2348031234567',
  status: 'consent_required',
  phone_verification_status: 'verified',
  consent_version: null,
  consent_at: null,
  created_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:00:00Z',
};

beforeEach(() => {
  mockConfirm.mockReset();
});

describe('CliVerifyConfirmScreen', () => {
  it('submits the entered code, calling onConfirmed', async () => {
    mockConfirm.mockResolvedValue(CONFIRMED);
    const onConfirmed = jest.fn();
    await render(
      <CliVerifyConfirmScreen
        accessToken="token"
        identityId="identity-1"
        phoneNumber="+2348031234567"
        onConfirmed={onConfirmed}
        onUseDifferentNumber={jest.fn()}
      />,
    );

    await fireEvent.changeText(screen.getByTestId('cli-confirm-code-input'), '123456');
    await fireEvent.press(screen.getByTestId('cli-confirm-submit'));

    expect(mockConfirm).toHaveBeenCalledWith('token', 'identity-1', '123456');
    expect(onConfirmed).toHaveBeenCalledWith(CONFIRMED);
  });

  it('shows an error for a wrong code without locking the input', async () => {
    mockConfirm.mockRejectedValue(
      new CliApiError('verification_code_invalid', 'That code did not match.'),
    );
    await render(
      <CliVerifyConfirmScreen
        accessToken="token"
        identityId="identity-1"
        phoneNumber="+2348031234567"
        onConfirmed={jest.fn()}
        onUseDifferentNumber={jest.fn()}
      />,
    );

    await fireEvent.changeText(screen.getByTestId('cli-confirm-code-input'), '111111');
    await fireEvent.press(screen.getByTestId('cli-confirm-submit'));

    expect(screen.getByTestId('cli-confirm-error')).toBeTruthy();
    expect(screen.getByText('That code did not match.')).toBeTruthy();
    expect(
      screen.getByTestId('cli-confirm-submit').props.accessibilityState.disabled,
    ).toBe(false);
  });

  it('locks further submission on a rate-limit response', async () => {
    mockConfirm.mockRejectedValue(
      new CliApiError('cli_verification_rate_limited', 'Too many attempts.'),
    );
    await render(
      <CliVerifyConfirmScreen
        accessToken="token"
        identityId="identity-1"
        phoneNumber="+2348031234567"
        onConfirmed={jest.fn()}
        onUseDifferentNumber={jest.fn()}
      />,
    );

    await fireEvent.changeText(screen.getByTestId('cli-confirm-code-input'), '111111');
    await fireEvent.press(screen.getByTestId('cli-confirm-submit'));

    expect(
      screen.getByTestId('cli-confirm-submit').props.accessibilityState.disabled,
    ).toBe(true);
  });

  it('calls onUseDifferentNumber', async () => {
    const onUseDifferentNumber = jest.fn();
    await render(
      <CliVerifyConfirmScreen
        accessToken="token"
        identityId="identity-1"
        phoneNumber="+2348031234567"
        onConfirmed={jest.fn()}
        onUseDifferentNumber={onUseDifferentNumber}
      />,
    );

    await fireEvent.press(screen.getByTestId('cli-confirm-use-different-number'));
    expect(onUseDifferentNumber).toHaveBeenCalledTimes(1);
  });
});
