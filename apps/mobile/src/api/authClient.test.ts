import {
  OtpApiError,
  refreshSession,
  requestOtp,
  requestPinRecovery,
  verifyOtp,
  verifyPinRecovery,
} from './authClient';

function mockFetchOnce(status: number, body: unknown, ok = status >= 200 && status < 300) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok,
    status,
    json: async () => body,
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
});

describe('requestOtp', () => {
  it('posts the phone number and returns the message on success', async () => {
    mockFetchOnce(200, { message: 'OTP sent' });

    const result = await requestOtp('08012345678');

    expect(result).toEqual({ message: 'OTP sent' });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/otp/request'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ phone_number: '08012345678' }),
      }),
    );
  });

  it('maps a 409 to an account_exists OtpApiError (AC-01.7)', async () => {
    mockFetchOnce(409, { error: 'account_exists', message: 'Please log in.' });

    await expect(requestOtp('08012345678')).rejects.toMatchObject({
      code: 'account_exists',
      message: 'Please log in.',
    });
  });

  it('maps a 429 to a rate_limited error with retryAfter (AC-01.9/PRD §5.1)', async () => {
    mockFetchOnce(429, {
      error: 'rate_limited',
      message: 'Please wait before requesting another code.',
      details: { retry_after: 30 },
    });

    const error = await requestOtp('08012345678').catch((err) => err);

    expect(error).toBeInstanceOf(OtpApiError);
    expect(error.code).toBe('rate_limited');
    expect(error.retryAfter).toBe(30);
  });

  it('maps a network failure to a network_error', async () => {
    (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('offline'));

    await expect(requestOtp('08012345678')).rejects.toMatchObject({ code: 'network_error' });
  });
});

describe('verifyOtp', () => {
  it('posts phone number, otp, and platform and returns the auth response', async () => {
    const authResponse = {
      access_token: 'a',
      refresh_token: 'b',
      is_new_user: true,
      user: {
        id: '1',
        phone_number: '+2348012345678',
        first_name: '',
        last_name: '',
        email: null,
        verified_cli: true,
        platform: 'android',
        status: 'active',
      },
    };
    mockFetchOnce(200, authResponse);

    const result = await verifyOtp('08012345678', '123456', 'android');

    expect(result).toEqual(authResponse);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/otp/verify'),
      expect.objectContaining({
        body: JSON.stringify({ phone_number: '08012345678', otp: '123456', platform: 'android' }),
      }),
    );
  });

  it('maps a 423 to a locked error with retryAfter (AC-01.5)', async () => {
    mockFetchOnce(423, {
      error: 'locked',
      message: 'Too many attempts. Please wait before trying again.',
      details: { retry_after: 60 },
    });

    const error = await verifyOtp('08012345678', '000000', 'android').catch((err) => err);

    expect(error.code).toBe('locked');
    expect(error.retryAfter).toBe(60);
  });

  it('maps a 400 otp_expired error (AC-01.4)', async () => {
    mockFetchOnce(400, { error: 'otp_expired', message: 'The verification code has expired.' });

    await expect(verifyOtp('08012345678', '000000', 'android')).rejects.toMatchObject({
      code: 'otp_expired',
    });
  });
});

describe('requestPinRecovery', () => {
  it('posts the phone number to the recovery endpoint (AC-23.4)', async () => {
    mockFetchOnce(200, { message: 'OTP sent' });

    const result = await requestPinRecovery('08012345678');

    expect(result).toEqual({ message: 'OTP sent' });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/pin/recovery/request'),
      expect.objectContaining({
        body: JSON.stringify({ phone_number: '08012345678' }),
      }),
    );
  });

  it('maps a 404 to an account_not_found error', async () => {
    mockFetchOnce(404, {
      error: 'account_not_found',
      message: 'No account exists for this phone number.',
    });

    await expect(requestPinRecovery('08012345678')).rejects.toMatchObject({
      code: 'account_not_found',
    });
  });
});

describe('verifyPinRecovery', () => {
  it('posts phone number, otp, and platform and returns the auth response', async () => {
    const authResponse = {
      access_token: 'a',
      refresh_token: 'b',
      is_new_user: false,
      user: {
        id: '1',
        phone_number: '+2348012345678',
        first_name: '',
        last_name: '',
        email: null,
        verified_cli: true,
        platform: 'android',
        status: 'active',
      },
    };
    mockFetchOnce(200, authResponse);

    const result = await verifyPinRecovery('08012345678', '123456', 'android');

    expect(result).toEqual(authResponse);
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/pin/recovery/verify'),
      expect.objectContaining({
        body: JSON.stringify({ phone_number: '08012345678', otp: '123456', platform: 'android' }),
      }),
    );
  });

  it('maps a 423 to a locked error with retryAfter', async () => {
    mockFetchOnce(423, {
      error: 'locked',
      message: 'Too many attempts. Please wait before trying again.',
      details: { retry_after: 60 },
    });

    const error = await verifyPinRecovery('08012345678', '000000', 'android').catch(
      (err) => err,
    );

    expect(error.code).toBe('locked');
    expect(error.retryAfter).toBe(60);
  });
});

describe('refreshSession', () => {
  it('posts the refresh token and returns a fresh access/refresh pair (AC-23.2)', async () => {
    mockFetchOnce(200, { access_token: 'new-access', refresh_token: 'new-refresh' });

    const result = await refreshSession('old-refresh');

    expect(result).toEqual({ access_token: 'new-access', refresh_token: 'new-refresh' });
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/token/refresh'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ refresh_token: 'old-refresh' }),
      }),
    );
  });

  it('maps a 401 to an invalid_refresh_token error the caller can distinguish from a transient failure', async () => {
    mockFetchOnce(401, {
      error: 'invalid_refresh_token',
      message: 'Refresh token is invalid or has been revoked.',
    });

    const error = await refreshSession('stale-refresh').catch((err) => err);

    expect(error).toBeInstanceOf(OtpApiError);
    expect(error.code).toBe('invalid_refresh_token');
  });
});
