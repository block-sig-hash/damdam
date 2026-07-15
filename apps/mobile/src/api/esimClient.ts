import { API_BASE_URL } from '../config/env';

export interface DeviceCompatibilityPayload {
  platform: 'ios' | 'android';
  device_model: string;
  os_version?: string;
  esim_supported: boolean;
}

export class EsimApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'EsimApiError';
  }
}

export async function logDeviceCompatibility(
  accessToken: string,
  payload: DeviceCompatibilityPayload,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/me/device-compatibility`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new EsimApiError('Check your connection and try again.');
  }
  if (!response.ok) {
    throw new EsimApiError('Could not save your device check. Please try again.');
  }
}
