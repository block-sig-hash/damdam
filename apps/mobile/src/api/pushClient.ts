import { API_BASE_URL } from '../config/env';

export async function registerDeviceToken(
  accessToken: string,
  fcmToken: string,
  platform: 'ios' | 'android',
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/me/device-token`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ fcm_token: fcmToken, platform }),
    });
  } catch {
    throw new Error('Push registration will retry when you are online.');
  }
  if (!response.ok) {
    throw new Error('Push registration will retry when you are online.');
  }
}
