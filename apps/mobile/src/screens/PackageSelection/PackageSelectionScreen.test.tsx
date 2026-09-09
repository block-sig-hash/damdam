import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { getPricingTiers, PricingApiError, PricingTier } from '../../api/pricingClient';
import { PackageSelectionScreen } from './PackageSelectionScreen';

jest.mock('../../api/pricingClient', () => {
  const actual = jest.requireActual('../../api/pricingClient');
  return { ...actual, getPricingTiers: jest.fn() };
});

const mockGetPricingTiers = getPricingTiers as jest.MockedFunction<typeof getPricingTiers>;

const tiers: PricingTier[] = [
  { id: 'starter', name: 'Starter', ngn_price: 65000, data_gb: 3, pstn_minutes: 20, is_group_tier: false },
  { id: 'basic', name: 'Basic', ngn_price: 95000, data_gb: 6, pstn_minutes: 45, is_group_tier: false },
  { id: 'standard', name: 'Standard', ngn_price: 145000, data_gb: 10, pstn_minutes: 90, is_group_tier: false },
  { id: 'family', name: 'Family', ngn_price: 75000, data_gb: 12, pstn_minutes: 100, is_group_tier: true, min_group_size: 2, max_group_size: 8, per_person_ngn_rate: 75000 },
];

beforeEach(() => {
  mockGetPricingTiers.mockReset();
});

describe('PackageSelectionScreen', () => {
  it('uses four card-shaped placeholders on first load', async () => {
    mockGetPricingTiers.mockImplementation(() => new Promise(() => undefined));

    await render(<PackageSelectionScreen onSelectTier={jest.fn()} />);

    expect(screen.getAllByTestId('pricing-skeleton-card')).toHaveLength(4);
  });

  it('shows all four current-price tier cards and the Standard badge (AC-08.1/2/3/6)', async () => {
    mockGetPricingTiers.mockResolvedValue(tiers);
    await render(<PackageSelectionScreen onSelectTier={jest.fn()} />);

    expect(await screen.findByText('Starter')).toBeTruthy();
    expect(screen.getByText('Basic')).toBeTruthy();
    expect(screen.getByText('Standard')).toBeTruthy();
    expect(screen.getByText('Family')).toBeTruthy();
    expect(screen.getByText('Recommended')).toBeTruthy();
    expect(screen.getByText('₦145,000')).toBeTruthy();
    expect(screen.getByText(/10 GB eSIM data/)).toBeTruthy();
    expect(screen.getByText(/90 Nigerian calling minutes/)).toBeTruthy();
    expect(screen.queryByText(/check-in|SOS/i)).toBeNull();
  });

  it("expands the What's included section (AC-08.5)", async () => {
    mockGetPricingTiers.mockResolvedValue(tiers);
    await render(<PackageSelectionScreen onSelectTier={jest.fn()} />);
    await screen.findByText('Starter');

    await act(async () => {
      fireEvent.press(screen.getByTestId('whats-included-toggle'));
    });

    expect(await screen.findByTestId('whats-included-content')).toBeTruthy();
    expect(screen.getByText(/Calls from your carrier-assigned number/)).toBeTruthy();
    expect(screen.queryByText(/check-in|SOS/i)).toBeNull();
  });

  it('hands a non-Family tier directly to the purchase seam', async () => {
    mockGetPricingTiers.mockResolvedValue(tiers);
    const onSelectTier = jest.fn();
    await render(<PackageSelectionScreen onSelectTier={onSelectTier} />);
    await screen.findByText('Starter');

    fireEvent.press(screen.getByTestId('tier-Basic'));

    expect(onSelectTier).toHaveBeenCalledWith(tiers[1]);
  });

  it('recalculates Family total live for stepper and direct entry from 2–8 (AC-08.4)', async () => {
    mockGetPricingTiers.mockResolvedValue(tiers);
    const onSelectTier = jest.fn();
    await render(<PackageSelectionScreen onSelectTier={onSelectTier} />);
    await screen.findByText('Family');

    await act(async () => {
      fireEvent.press(screen.getByTestId('tier-Family'));
    });
    expect(await screen.findByTestId('family-total-price')).toHaveTextContent('₦150,000');

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('family-size-input'), '9');
    });
    expect(screen.getByTestId('family-total-price')).toHaveTextContent('—');
    expect(screen.getByText('Enter a number from 2 to 8.')).toBeTruthy();
    expect(screen.getByTestId('family-size-continue').props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: true }),
    );

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('family-size-input'), '2');
    });

    await act(async () => {
      fireEvent.press(screen.getByTestId('family-size-increment'));
    });
    await waitFor(() =>
      expect(screen.getByTestId('family-total-price')).toHaveTextContent('₦225,000'),
    );

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('family-size-input'), '8');
    });
    await waitFor(() =>
      expect(screen.getByTestId('family-total-price')).toHaveTextContent('₦600,000'),
    );

    await act(async () => {
      fireEvent.press(screen.getByTestId('family-size-continue'));
    });
    expect(onSelectTier).toHaveBeenCalledWith(tiers[3], 8);
  });

  it('blocks on pricing failure and retries without stale cards', async () => {
    mockGetPricingTiers
      .mockRejectedValueOnce(new PricingApiError('Check your connection and try again.'))
      .mockResolvedValueOnce(tiers);
    await render(<PackageSelectionScreen onSelectTier={jest.fn()} />);

    expect(await screen.findByTestId('pricing-error-screen')).toBeTruthy();
    expect(screen.queryByText('Starter')).toBeNull();

    await act(async () => {
      fireEvent.press(screen.getByTestId('pricing-retry'));
    });
    await waitFor(() => expect(screen.getByText('Starter')).toBeTruthy());
    expect(mockGetPricingTiers).toHaveBeenCalledTimes(2);
  });

  it('fails closed instead of showing a partial catalogue', async () => {
    mockGetPricingTiers.mockResolvedValue(tiers.slice(0, 3));

    await render(<PackageSelectionScreen onSelectTier={jest.fn()} />);

    expect(await screen.findByTestId('pricing-error-screen')).toBeTruthy();
    expect(screen.queryByTestId('tier-Starter')).toBeNull();
  });
});
