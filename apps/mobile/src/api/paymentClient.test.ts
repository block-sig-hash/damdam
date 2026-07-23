import {
  getPackageGeofence,
  getPackageStatus,
  initializePurchase,
} from './paymentClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => fetchMock.mockReset());

describe('paymentClient', () => {
  it('AC-09.1: initializes a processor-neutral checkout with the selected group size', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        package_id: 'package-1',
        processor: 'flutterwave',
        processor_reference: 'reference-1',
        checkout_url: 'https://checkout.example/reference-1',
      }),
    });

    const checkout = await initializePurchase('token', 'family', 4);

    expect(checkout.checkout_url).toContain('https://checkout.example');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/packages/purchase'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
        body: JSON.stringify({ pricing_tier_id: 'family', group_size: 4 }),
      }),
    );
  });

  it('AC-13.1: fetches package-owned destination geofence configuration', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        latitude: 21.4858,
        longitude: 39.1925,
        radius_meters: 150000,
        request_id: 'arrival-sa-package-1',
      }),
    });

    await expect(getPackageGeofence('token', 'package-1')).resolves.toEqual(
      expect.objectContaining({ request_id: 'arrival-sa-package-1' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/packages/package-1/geofence'),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
      }),
    );
  });

  it('AC-09.3/4: exposes package status and server failure reasons', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: false,
        json: async () => ({ message: 'Both payment services are unavailable.' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          status: 'active',
          data_gb_total: 10,
          data_gb_remaining: 2,
          pstn_minutes_total: 90,
          pstn_minutes_remaining: 4,
        }),
      });

    await expect(initializePurchase('token', 'standard')).rejects.toThrow(
      'The payment was not completed.',
    );
    await expect(getPackageStatus('token', 'package-1')).resolves.toEqual(
      expect.objectContaining({
        data_gb_total: 10,
        data_gb_remaining: 2,
        pstn_minutes_total: 90,
        pstn_minutes_remaining: 4,
      }),
    );
  });
});
