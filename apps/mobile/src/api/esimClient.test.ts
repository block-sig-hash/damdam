import {
  EsimApiError,
  getEsim,
  issueEsim,
  logDeviceCompatibility,
  markEsimDownloaded,
  markEsimActivated,
} from './esimClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => fetchMock.mockReset());

describe('esimClient', () => {
  it('AC-10.1: posts the compatibility check with platform, model, os_version', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ logged: true }) });

    await logDeviceCompatibility('token', {
      platform: 'ios',
      device_model: 'iPhone 15',
      os_version: '18.1',
      esim_supported: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/me/device-compatibility'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer token' }),
        body: JSON.stringify({
          platform: 'ios',
          device_model: 'iPhone 15',
          os_version: '18.1',
          esim_supported: true,
        }),
      }),
    );
  });

  it('throws EsimApiError on a network failure', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));

    await expect(
      logDeviceCompatibility('token', {
        platform: 'android',
        device_model: 'Tecno Spark 10',
        esim_supported: false,
      }),
    ).rejects.toThrow(EsimApiError);
  });

  it('throws EsimApiError on a non-ok response', async () => {
    fetchMock.mockResolvedValue({ ok: false, json: async () => ({}) });

    await expect(
      logDeviceCompatibility('token', {
        platform: 'android',
        device_model: 'Tecno Spark 10',
        esim_supported: false,
      }),
    ).rejects.toThrow(EsimApiError);
  });

  it('AC-11.2/11.3: calls the issue and profile contracts without vendor details', async () => {
    const profile = {
      esim_profile_id: 'profile-1',
      iccid: '8944501234567890123456',
      activation_code_lpa: 'LPA:1$server$match',
      qr_code_url: 'https://cdn.example/qr.png',
      status: 'issued',
    };
    fetchMock.mockResolvedValue({ ok: true, json: async () => profile });

    await expect(issueEsim('token', 'package-1')).resolves.toEqual(profile);
    await expect(getEsim('token', 'package-1')).resolves.toEqual(profile);

    expect(fetchMock.mock.calls[0][0]).toContain('/packages/package-1/esim/issue');
    expect(fetchMock.mock.calls[0][1].method).toBe('POST');
    expect(fetchMock.mock.calls[1][0]).toContain('/packages/package-1/esim');
    expect(fetchMock.mock.calls[1][1].method).toBe('GET');
  });

  it('AC-11.4: marks the one package profile downloaded', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'downloaded' }),
    });

    await expect(markEsimDownloaded('token', 'package-1')).resolves.toEqual({
      status: 'downloaded',
    });
    expect(fetchMock.mock.calls[0][0]).toContain(
      '/packages/package-1/esim/mark-downloaded',
    );
  });

  it('AC-13.6: marks a package profile activated only after client validation', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({ status: 'activated' }) });

    await expect(markEsimActivated('token', 'package-1')).resolves.toEqual({
      status: 'activated',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/packages/package-1/esim/mark-activated'),
      expect.objectContaining({ method: 'POST' }),
    );
  });
});
