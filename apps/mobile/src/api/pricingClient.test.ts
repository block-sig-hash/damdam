import { getPricingTiers, PricingApiError } from './pricingClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => {
  fetchMock.mockReset();
});

describe('pricingClient', () => {
  it('reads public pricing without auth headers or client-side FX inputs (AC-08.6)', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        tiers: [
          {
            id: 'standard-id',
            name: 'Standard',
            ngn_price: 145000,
            data_gb: 10,
            pstn_minutes: 90,
            is_group_tier: false,
          },
        ],
      }),
    });

    const tiers = await getPricingTiers();

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/v1/pricing/tiers',
    );
    expect(tiers[0].ngn_price).toBe(145000);
  });

  it('uses a blocking connection error instead of stale cached pricing', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));

    await expect(getPricingTiers()).rejects.toEqual(
      new PricingApiError('Check your connection and try again.'),
    );
  });
});
