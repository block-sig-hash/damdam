import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { previewActivationCode, redeemActivationCode } from '../api/activationClient';
import { requestOtp, verifyOtp } from '../api/authClient';
import { OnboardingNavigator } from './OnboardingNavigator';

jest.mock('../api/authClient', () => {
  const actual = jest.requireActual('../api/authClient');
  return { ...actual, requestOtp: jest.fn(), verifyOtp: jest.fn() };
});
jest.mock('../api/activationClient', () => {
  const actual = jest.requireActual('../api/activationClient');
  return {
    ...actual,
    previewActivationCode: jest.fn(),
    redeemActivationCode: jest.fn(),
  };
});

const mockRequestOtp = requestOtp as jest.MockedFunction<typeof requestOtp>;
const mockVerifyOtp = verifyOtp as jest.MockedFunction<typeof verifyOtp>;
const mockPreview = previewActivationCode as jest.MockedFunction<
  typeof previewActivationCode
>;
const mockRedeem = redeemActivationCode as jest.MockedFunction<
  typeof redeemActivationCode
>;

beforeEach(() => {
  mockRequestOtp.mockReset();
  mockVerifyOtp.mockReset();
  mockPreview.mockReset();
  mockRedeem.mockReset();
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
    expect(screen.getByText('Package active')).toBeTruthy();
  });
});
