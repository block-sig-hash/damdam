import { EsimApiError, logDeviceCompatibility } from './esimClient';

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
});
