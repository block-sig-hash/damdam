import { registerDeviceToken } from './pushClient';

const fetchMock = jest.fn();
global.fetch = fetchMock;

beforeEach(() => fetchMock.mockReset());

it('AC-13.1: uploads the FCM app installation against the authenticated pilgrim', async () => {
  fetchMock.mockResolvedValue({ ok: true });
  await registerDeviceToken('access', 'fcm-registration-token-long-enough', 'android');
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining('/me/device-token'),
    expect.objectContaining({
      method: 'PUT',
      headers: expect.objectContaining({ Authorization: 'Bearer access' }),
      body: JSON.stringify({
        fcm_token: 'fcm-registration-token-long-enough',
        platform: 'android',
      }),
    }),
  );
});

it('keeps push registration non-blocking when offline', async () => {
  fetchMock.mockRejectedValue(new Error('offline'));
  await expect(
    registerDeviceToken('access', 'fcm-registration-token-long-enough', 'ios'),
  ).rejects.toThrow(/retry when you are online/);
});
