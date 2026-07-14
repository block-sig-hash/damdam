import { PinApiError, setPin } from './pinClient';

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

describe('pin API client', () => {
  it('sets the PIN with pilgrim authentication', async () => {
    mockFetchOnce(200, { message: 'PIN set' });

    await expect(setPin('access-token', '4682')).resolves.toEqual({ message: 'PIN set' });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/pin/set'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer access-token' }),
        body: JSON.stringify({ pin: '4682' }),
      }),
    );
  });

  it('surfaces a weak PIN as a typed API error (AC-02.1)', async () => {
    mockFetchOnce(400, {
      error: 'pin_too_weak',
      message: 'Choose a non-repeated, non-sequential 4-digit PIN.',
    });

    const error = await setPin('access-token', '1234').catch((caught) => caught);

    expect(error).toBeInstanceOf(PinApiError);
    expect(error.code).toBe('pin_too_weak');
  });

  it('maps network failures without losing a typed retry signal', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));

    await expect(setPin('access-token', '4682')).rejects.toMatchObject({
      code: 'network_error',
    });
  });
});
