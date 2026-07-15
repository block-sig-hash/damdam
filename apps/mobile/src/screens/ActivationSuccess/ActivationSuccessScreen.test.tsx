import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { ActivationApiError, redeemActivationCode } from '../../api/activationClient';
import { ActivationSuccessScreen } from './ActivationSuccessScreen';

jest.mock('../../api/activationClient', () => {
  const actual = jest.requireActual('../../api/activationClient');
  return { ...actual, redeemActivationCode: jest.fn() };
});

const mockRedeem = redeemActivationCode as jest.MockedFunction<
  typeof redeemActivationCode
>;

beforeEach(() => {
  mockRedeem.mockReset();
});

describe('ActivationSuccessScreen', () => {
  it('shows the package summary once redemption succeeds (AC-07.4/AC-07.6)', async () => {
    mockRedeem.mockResolvedValue({
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    });

    await act(async () => {
      render(
        <ActivationSuccessScreen
          accessToken="token"
          activationCode="ABCD1234"
          onContinue={jest.fn()}
        />,
      );
    });

    expect(await screen.findByTestId('activation-success')).toBeTruthy();
    expect(screen.getByText('10 GB')).toBeTruthy();
    expect(screen.getByText('60 minutes')).toBeTruthy();
  });

  it('shows a retryable error state when redemption fails', async () => {
    mockRedeem.mockRejectedValue(
      new ActivationApiError(
        'activation_code_already_used',
        'This activation code has already been used.',
      ),
    );

    await act(async () => {
      render(
        <ActivationSuccessScreen
          accessToken="token"
          activationCode="ABCD1234"
          onContinue={jest.fn()}
        />,
      );
    });

    expect(screen.getByTestId('activation-redeem-error')).toBeTruthy();
    expect(screen.getByTestId('activation-redeem-retry')).toBeTruthy();
  });

  it('calls onContinue when the pilgrim taps Continue', async () => {
    mockRedeem.mockResolvedValue({
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    });
    const onContinue = jest.fn();

    await act(async () => {
      render(
        <ActivationSuccessScreen
          accessToken="token"
          activationCode="ABCD1234"
          onContinue={onContinue}
        />,
      );
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('activation-success-continue'));
    });

    expect(onContinue).toHaveBeenCalledWith(expect.objectContaining({ package_id: 'package-1' }));
  });
});
