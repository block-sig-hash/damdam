import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { AuthResponse, OtpApiError, verifyOtp } from '../../api/authClient';
import { OTPVerificationScreen } from './OTPVerificationScreen';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return { ...actual, verifyOtp: jest.fn() };
});

const mockVerifyOtp = verifyOtp as jest.MockedFunction<typeof verifyOtp>;

const AUTH_RESPONSE: AuthResponse = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  is_new_user: true,
  user: {
    id: 'user-1',
    phone_number: '+2348012345678',
    first_name: '',
    last_name: '',
    email: null,
    verified_cli: true,
    platform: 'android',
    status: 'active',
  },
};

beforeEach(() => {
  mockVerifyOtp.mockReset();
});

describe('OTPVerificationScreen', () => {
  it('auto-submits once 6 digits are entered and calls onVerified (AC-01.6)', async () => {
    mockVerifyOtp.mockResolvedValue(AUTH_RESPONSE);
    const onVerified = jest.fn();
    await render(<OTPVerificationScreen phoneNumber="08012345678" onVerified={onVerified} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    expect(mockVerifyOtp).toHaveBeenCalledWith('08012345678', '123456', expect.any(String));
    expect(onVerified).toHaveBeenCalledWith(AUTH_RESPONSE);
  });

  it('shows an inline error banner on an incorrect code (AC-01.5)', async () => {
    mockVerifyOtp.mockRejectedValue(
      new OtpApiError('invalid_otp', 'The verification code is incorrect.'),
    );
    await render(<OTPVerificationScreen phoneNumber="08012345678" onVerified={jest.fn()} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '000000');
    });

    expect(screen.getByTestId('otp-error-banner')).toBeTruthy();
    expect(screen.getByText('That code is incorrect. Try again.')).toBeTruthy();
  });
});
