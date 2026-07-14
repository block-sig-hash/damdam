import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { previewActivationCode, redeemActivationCode } from '../api/activationClient';
import {
  OtpApiError,
  requestOtp,
  requestPinRecovery,
  verifyOtp,
  verifyPinRecovery,
} from '../api/authClient';
import { setPin } from '../api/pinClient';
import { savePinLocally } from '../utils/pinLocalStore';
import { OnboardingNavigator } from './OnboardingNavigator';

jest.mock('../api/authClient', () => {
  const actual = jest.requireActual('../api/authClient');
  return {
    ...actual,
    requestOtp: jest.fn(),
    verifyOtp: jest.fn(),
    requestPinRecovery: jest.fn(),
    verifyPinRecovery: jest.fn(),
  };
});
jest.mock('../api/activationClient', () => {
  const actual = jest.requireActual('../api/activationClient');
  return {
    ...actual,
    previewActivationCode: jest.fn(),
    redeemActivationCode: jest.fn(),
  };
});
jest.mock('../api/pinClient', () => {
  const actual = jest.requireActual('../api/pinClient');
  return {
    ...actual,
    setPin: jest.fn(),
  };
});
jest.mock('../utils/pinLocalStore', () => ({
  ...jest.requireActual('../utils/pinLocalStore'),
  savePinLocally: jest.fn(),
}));

const mockRequestOtp = requestOtp as jest.MockedFunction<typeof requestOtp>;
const mockVerifyOtp = verifyOtp as jest.MockedFunction<typeof verifyOtp>;
const mockRequestPinRecovery = requestPinRecovery as jest.MockedFunction<
  typeof requestPinRecovery
>;
const mockVerifyPinRecovery = verifyPinRecovery as jest.MockedFunction<
  typeof verifyPinRecovery
>;
const mockPreview = previewActivationCode as jest.MockedFunction<
  typeof previewActivationCode
>;
const mockRedeem = redeemActivationCode as jest.MockedFunction<
  typeof redeemActivationCode
>;
const mockSetPin = setPin as jest.MockedFunction<typeof setPin>;
const mockSaveLocally = savePinLocally as jest.MockedFunction<typeof savePinLocally>;

beforeEach(() => {
  mockRequestOtp.mockReset();
  mockVerifyOtp.mockReset();
  mockRequestPinRecovery.mockReset();
  mockVerifyPinRecovery.mockReset();
  mockPreview.mockReset();
  mockRedeem.mockReset();
  mockSetPin.mockReset();
  mockSaveLocally.mockReset();
  mockSaveLocally.mockResolvedValue(undefined);
});

describe('OnboardingNavigator', () => {
  it('starts at Phone Entry when no activation code is present (Flow A unchanged)', async () => {
    await render(<OnboardingNavigator />);

    expect(screen.getByTestId('phone-entry-input')).toBeTruthy();
  });

  it('carries an activation code through Phone Entry and OTP into auto-redemption (Flow B, AC-07.4)', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    mockRequestOtp.mockResolvedValue({ message: 'OTP sent' });
    mockVerifyOtp.mockResolvedValue({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      is_new_user: true,
      user: {
        id: 'user-1',
        phone_number: '+2348012345678',
        first_name: '',
        last_name: '',
        email: null,
        verified_cli: false,
        platform: 'android',
        status: 'active',
      },
    });
    mockRedeem.mockResolvedValue({
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    });

    await act(async () => {
      render(<OnboardingNavigator initialActivationCode="ABCD1234" />);
    });

    // Activation Code Entry: deep-linked code is pre-filled and
    // auto-checked, landing the pilgrim on Continue.
    expect(await screen.findByTestId('activation-preview-card')).toBeTruthy();
    await act(async () => {
      fireEvent.press(screen.getByTestId('activation-code-continue'));
    });

    // Phone Entry → OTP, same screens Flow A uses.
    expect(screen.getByTestId('phone-entry-input')).toBeTruthy();
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('phone-entry-input'), '08012345678');
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('phone-entry-submit'));
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    // Landing on Activation Success means redemption already fired
    // automatically — no separate "enter your code again" step.
    expect(await screen.findByTestId('activation-success')).toBeTruthy();
    expect(mockRedeem).toHaveBeenCalledWith('access-token', 'ABCD1234');
    expect(screen.getByText('10 GB')).toBeTruthy();

    await act(async () => {
      fireEvent.press(screen.getByTestId('activation-success-continue'));
    });

    // Activation success now leads into PIN Setup (US-02), not
    // straight to a placeholder — same PIN Setup screen Flow A uses.
    expect(screen.getByTestId('pin-setup-input')).toBeTruthy();
    mockSetPin.mockResolvedValue({ message: 'PIN set' });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '4682');
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '4682');
    });

    expect(mockSetPin).toHaveBeenCalledWith('access-token', '4682');
    expect(await screen.findByText('PIN set')).toBeTruthy();
  });

  it('routes an existing account to re-authentication, carrying the activation code through (AC-01.7/AC-07.5)', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    mockRequestOtp.mockRejectedValue(
      new OtpApiError('account_exists', 'This number already has an account. Please log in.'),
    );
    mockRequestPinRecovery.mockResolvedValue({ message: 'OTP sent' });
    mockVerifyPinRecovery.mockResolvedValue({
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
        platform: 'android',
        status: 'active',
      },
    });
    mockRedeem.mockResolvedValue({
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    });

    await act(async () => {
      render(<OnboardingNavigator initialActivationCode="ABCD1234" />);
    });
    expect(await screen.findByTestId('activation-preview-card')).toBeTruthy();
    await act(async () => {
      fireEvent.press(screen.getByTestId('activation-code-continue'));
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('phone-entry-input'), '08012345678');
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('phone-entry-submit'));
    });

    // account_exists routes to ReturningPilgrimScreen instead of OTP
    // Verification — same 6-digit input, different backend flow.
    expect(mockRequestPinRecovery).toHaveBeenCalledWith('08012345678');
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    expect(mockVerifyPinRecovery).toHaveBeenCalledWith('08012345678', '123456', expect.any(String));
    expect(await screen.findByTestId('activation-success')).toBeTruthy();
    expect(mockRedeem).toHaveBeenCalledWith('access-token', 'ABCD1234');

    // A returning pilgrim already has a PIN — activation success must
    // not route them back through PIN Setup.
    await act(async () => {
      fireEvent.press(screen.getByTestId('activation-success-continue'));
    });
    expect(screen.queryByTestId('pin-setup-input')).toBeNull();
    expect(mockSetPin).not.toHaveBeenCalled();
  });

  it('skips PIN Setup entirely for a returning pilgrim with no activation code (AC-02.3)', async () => {
    mockRequestOtp.mockRejectedValue(
      new OtpApiError('account_exists', 'This number already has an account. Please log in.'),
    );
    mockRequestPinRecovery.mockResolvedValue({ message: 'OTP sent' });
    mockVerifyPinRecovery.mockResolvedValue({
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
        platform: 'android',
        status: 'active',
      },
    });

    await render(<OnboardingNavigator />);
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('phone-entry-input'), '08012345678');
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('phone-entry-submit'));
    });
    expect(mockRequestPinRecovery).toHaveBeenCalledWith('08012345678');
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    // Lands straight on the (placeholder) Home destination, never on
    // PIN Setup — this pilgrim already has a PIN from their original
    // signup, so re-authenticating must not ask them to set a new one.
    expect(await screen.findByText('Welcome back')).toBeTruthy();
    expect(screen.queryByTestId('pin-setup-input')).toBeNull();
    expect(mockSetPin).not.toHaveBeenCalled();
  });

  it('sends a brand-new pilgrim through PIN Setup with no activation code (Flow A, AC-02.1)', async () => {
    mockRequestOtp.mockResolvedValue({ message: 'OTP sent' });
    mockVerifyOtp.mockResolvedValue({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      is_new_user: true,
      user: {
        id: 'user-1',
        phone_number: '+2348012345678',
        first_name: '',
        last_name: '',
        email: null,
        verified_cli: false,
        platform: 'android',
        status: 'active',
      },
    });

    await render(<OnboardingNavigator />);
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('phone-entry-input'), '08012345678');
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('phone-entry-submit'));
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    expect(screen.getByTestId('pin-setup-input')).toBeTruthy();
  });
});
