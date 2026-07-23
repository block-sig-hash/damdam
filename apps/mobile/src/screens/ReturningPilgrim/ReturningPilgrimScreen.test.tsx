import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { OtpApiError, requestPinRecovery, verifyPinRecovery } from '../../api/authClient';
import { ReturningPilgrimScreen } from './ReturningPilgrimScreen';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return { ...actual, requestPinRecovery: jest.fn(), verifyPinRecovery: jest.fn() };
});

const mockRequest = requestPinRecovery as jest.MockedFunction<typeof requestPinRecovery>;
const mockVerify = verifyPinRecovery as jest.MockedFunction<typeof verifyPinRecovery>;

const AUTH_RESPONSE = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  is_new_user: false,
  user: {
    id: 'user-1',
    phone_number: '+2348012345678',
    first_name: '',
    last_name: '',
    email: null,
    verified_cli: true,
    locale: 'en' as const,
    platform: 'android',
    status: 'active',
  },
};

beforeEach(() => {
  mockRequest.mockReset();
  mockVerify.mockReset();
});

describe('ReturningPilgrimScreen', () => {
  it('sends a code on mount and auto-submits once 6 digits are entered', async () => {
    mockRequest.mockResolvedValue({ message: 'OTP sent' });
    mockVerify.mockResolvedValue(AUTH_RESPONSE);
    const onVerified = jest.fn();

    await act(async () => {
      render(<ReturningPilgrimScreen phoneNumber="08012345678" onVerified={onVerified} />);
    });

    expect(mockRequest).toHaveBeenCalledWith('08012345678', 'en');

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    expect(mockVerify).toHaveBeenCalledWith(
      '08012345678',
      '123456',
      expect.any(String),
      'en',
    );
    expect(onVerified).toHaveBeenCalledWith(AUTH_RESPONSE);
  });

  it('shows an inline error banner on an incorrect code', async () => {
    mockRequest.mockResolvedValue({ message: 'OTP sent' });
    mockVerify.mockRejectedValue(
      new OtpApiError('invalid_otp', 'That code is incorrect.'),
    );

    await act(async () => {
      render(
        <ReturningPilgrimScreen phoneNumber="08012345678" onVerified={jest.fn()} />,
      );
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '000000');
    });

    expect(screen.getByTestId('returning-pilgrim-error-banner')).toBeTruthy();
  });
});
