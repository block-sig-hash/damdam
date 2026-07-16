import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { getPackageStatus, initializePurchase } from '../../api/paymentClient';
import { RetailPurchaseFlow } from './RetailPurchaseFlow';

jest.mock('../../api/pricingClient', () => ({
  getPricingTiers: jest.fn().mockResolvedValue([
    { id: 'starter', name: 'Starter', ngn_price: 65000, data_gb: 3, pstn_minutes: 20, is_group_tier: false },
    { id: 'basic', name: 'Basic', ngn_price: 95000, data_gb: 6, pstn_minutes: 45, is_group_tier: false },
    { id: 'standard', name: 'Standard', ngn_price: 145000, data_gb: 10, pstn_minutes: 90, is_group_tier: false },
    { id: 'family', name: 'Family', ngn_price: 75000, data_gb: 12, pstn_minutes: 100, is_group_tier: true, min_group_size: 2, max_group_size: 8, per_person_ngn_rate: 75000 },
  ]),
}));
jest.mock('../../api/paymentClient', () => ({
  initializePurchase: jest.fn(),
  getPackageStatus: jest.fn(),
}));
jest.mock('react-native-webview', () => {
  const ReactModule = require('react');
  const { Pressable, Text, View } = require('react-native');
  return {
    WebView: ({ source, onError }: { source: { uri: string }; onError: () => void }) =>
      ReactModule.createElement(
        View,
        { testID: 'payment-webview' },
        ReactModule.createElement(Text, null, source.uri),
        ReactModule.createElement(
          Pressable,
          { testID: 'webview-error', onPress: onError },
          ReactModule.createElement(Text, null, 'fail'),
        ),
      ),
  };
}, { virtual: true });

const mockInitialize = initializePurchase as jest.MockedFunction<typeof initializePurchase>;
const mockStatus = getPackageStatus as jest.MockedFunction<typeof getPackageStatus>;

beforeEach(() => {
  jest.useRealTimers();
  mockInitialize.mockReset();
  mockStatus.mockReset();
});

describe('RetailPurchaseFlow', () => {
  it('AC-09.1/2: opens the returned checkout URL without exposing processor choice', async () => {
    mockInitialize.mockResolvedValue({
      package_id: 'package-1',
      processor: 'paystack',
      processor_reference: 'reference-1',
      checkout_url: 'https://checkout.example/reference-1',
    });
    mockStatus.mockResolvedValue({
      status: 'pending', data_gb_total: 10, data_gb_remaining: 0,
      pstn_minutes_total: 90, pstn_minutes_remaining: 0,
    });

    await render(<RetailPurchaseFlow accessToken="token" />);
    await act(async () => fireEvent.press(await screen.findByTestId('tier-Standard')));

    expect(await screen.findByTestId('payment-webview')).toBeTruthy();
    expect(screen.getByText('https://checkout.example/reference-1')).toBeTruthy();
    expect(screen.queryByText(/Paystack|Flutterwave/)).toBeNull();
    expect(mockInitialize).toHaveBeenCalledWith('token', 'standard', undefined);
  });

  it('AC-09.3: shows success as soon as backend confirmation is observed', async () => {
    mockInitialize.mockResolvedValue({
      package_id: 'package-1',
      processor: 'paystack',
      processor_reference: 'reference-1',
      checkout_url: 'https://checkout.example/reference-1',
    });
    mockStatus.mockResolvedValue({
      status: 'active', data_gb_total: 10, data_gb_remaining: 10,
      pstn_minutes_total: 90, pstn_minutes_remaining: 90,
    });

    await render(<RetailPurchaseFlow accessToken="token" />);
    await act(async () => fireEvent.press(await screen.findByTestId('tier-Standard')));

    expect(await screen.findByText('Payment successful')).toBeTruthy();
    expect(screen.getByText(/10 GB/)).toBeTruthy();
  });

  it('AC-09.4: shows initialization failure and retries the same selection', async () => {
    mockInitialize
      .mockRejectedValueOnce(new Error('Payment could not be started.'))
      .mockResolvedValueOnce({
        package_id: 'package-1',
        processor: 'paystack',
        processor_reference: 'reference-1',
        checkout_url: 'https://checkout.example/reference-1',
      });
    mockStatus.mockResolvedValue({
      status: 'pending', data_gb_total: 6, data_gb_remaining: 0,
      pstn_minutes_total: 45, pstn_minutes_remaining: 0,
    });

    await render(<RetailPurchaseFlow accessToken="token" />);
    await act(async () => fireEvent.press(await screen.findByTestId('tier-Basic')));
    expect(await screen.findByText('Payment could not be started.')).toBeTruthy();

    await act(async () => fireEvent.press(screen.getByTestId('payment-retry')));

    expect(await screen.findByTestId('payment-webview')).toBeTruthy();
    expect(mockInitialize).toHaveBeenCalledTimes(2);
  });

  it('AC-09.4: replaces a failed web view with a clear retry action', async () => {
    mockInitialize.mockResolvedValue({
      package_id: 'package-1',
      processor: 'paystack',
      processor_reference: 'reference-1',
      checkout_url: 'https://checkout.example/reference-1',
    });
    mockStatus.mockResolvedValue({
      status: 'pending', data_gb_total: 3, data_gb_remaining: 0,
      pstn_minutes_total: 20, pstn_minutes_remaining: 0,
    });

    await render(<RetailPurchaseFlow accessToken="token" />);
    await act(async () => fireEvent.press(await screen.findByTestId('tier-Starter')));
    fireEvent.press(await screen.findByTestId('webview-error'));

    await waitFor(() => expect(screen.getByTestId('payment-retry')).toBeTruthy());
    expect(screen.getByText(/checkout page could not load/i)).toBeTruthy();
  });

  it('§5.3: polls every 10 seconds until a delayed webhook activates the package', async () => {
    jest.useFakeTimers();
    mockInitialize.mockResolvedValue({
      package_id: 'package-1',
      processor: 'paystack',
      processor_reference: 'reference-1',
      checkout_url: 'https://checkout.example/reference-1',
    });
    mockStatus
      .mockResolvedValueOnce({
        status: 'pending', data_gb_total: 10, data_gb_remaining: 0,
        pstn_minutes_total: 90, pstn_minutes_remaining: 0,
      })
      .mockResolvedValueOnce({
        status: 'active', data_gb_total: 10, data_gb_remaining: 10,
        pstn_minutes_total: 90, pstn_minutes_remaining: 90,
      });

    await render(<RetailPurchaseFlow accessToken="token" />);
    await act(async () => fireEvent.press(await screen.findByTestId('tier-Standard')));
    expect(await screen.findByTestId('payment-webview')).toBeTruthy();

    await act(async () => {
      jest.advanceTimersByTime(10_000);
      await Promise.resolve();
    });

    expect(await screen.findByText('Payment successful')).toBeTruthy();
    expect(mockStatus).toHaveBeenCalledTimes(2);
  });
});
