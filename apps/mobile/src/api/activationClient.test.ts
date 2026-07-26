import {
  ActivationApiError,
  previewActivationCode,
  redeemActivationCode,
} from './activationClient';

function mockFetchOnce(status: number, body: unknown) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
});

describe('activation API client', () => {
  it('previews a valid code without authentication (AC-07.2)', async () => {
    const preview = {
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    };
    mockFetchOnce(200, preview);

    await expect(previewActivationCode('ABCD1234')).resolves.toEqual(preview);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/activation/ABCD1234'),
      { headers: { 'Accept-Language': 'en' } },
    );
    const [, options] = (global.fetch as jest.Mock).mock.calls[0];
    expect(options).toEqual({ headers: { 'Accept-Language': 'en' } });
  });

  it('surfaces an unknown code as a typed 404 error', async () => {
    mockFetchOnce(404, {
      error: 'activation_code_invalid',
      message: 'This activation code is invalid.',
    });

    const error = await previewActivationCode('NOTREAL').catch((caught) => caught);

    expect(error).toBeInstanceOf(ActivationApiError);
    expect(error.code).toBe('activation_code_invalid');
  });

  it('redeems a code with the pilgrim access token (AC-07.4/AC-07.5)', async () => {
    const redemption = {
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    };
    mockFetchOnce(200, redemption);

    await expect(
      redeemActivationCode('access-token', 'ABCD1234'),
    ).resolves.toEqual(redemption);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/me/activation/redeem'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
        body: JSON.stringify({ activation_code: 'ABCD1234' }),
      }),
    );
  });

  it('surfaces a phone mismatch as a typed, non-retryable error', async () => {
    mockFetchOnce(403, {
      error: 'activation_code_phone_mismatch',
      message: 'This activation code was issued to a different phone number.',
    });

    const error = await redeemActivationCode('access-token', 'ABCD1234').catch(
      (caught) => caught,
    );

    expect(error).toBeInstanceOf(ActivationApiError);
    expect(error.code).toBe('activation_code_phone_mismatch');
  });

  it('maps network failures to a retryable network_error code', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));

    await expect(
      redeemActivationCode('access-token', 'ABCD1234'),
    ).rejects.toMatchObject({ code: 'network_error' });
  });
});
