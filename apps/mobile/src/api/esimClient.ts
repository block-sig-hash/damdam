import { API_BASE_URL } from '../config/env';

export interface DeviceCompatibilityPayload {
  platform: 'ios' | 'android';
  device_model: string;
  os_version?: string;
  esim_supported: boolean;
}

export interface EsimProfile {
  esim_profile_id: string;
  iccid: string;
  activation_code_lpa?: string;
  qr_code_url: string;
  status: 'issued' | 'downloaded' | 'activated';
  downloaded_at?: string | null;
  activated_at?: string | null;
}

export interface EsimStatusResponse {
  status: 'downloaded';
}

export class EsimApiError extends Error {
  constructor(message: string, readonly code?: string) {
    super(message);
    this.name = 'EsimApiError';
  }
}

async function profileRequest<T>(
  accessToken: string,
  path: string,
  method: 'GET' | 'POST',
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    throw new EsimApiError('Check your connection and try again.', 'network_error');
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: string;
      message?: string;
    };
    throw new EsimApiError(
      payload.message ?? 'Your eSIM is not available yet. Please try again.',
      payload.error,
    );
  }
  return response.json() as Promise<T>;
}

export function issueEsim(accessToken: string, packageId: string): Promise<EsimProfile> {
  return profileRequest<EsimProfile>(accessToken, `/packages/${packageId}/esim/issue`, 'POST');
}

export function getEsim(accessToken: string, packageId: string): Promise<EsimProfile> {
  return profileRequest<EsimProfile>(accessToken, `/packages/${packageId}/esim`, 'GET');
}

export function markEsimDownloaded(
  accessToken: string,
  packageId: string,
): Promise<EsimStatusResponse> {
  return profileRequest<EsimStatusResponse>(
    accessToken,
    `/packages/${packageId}/esim/mark-downloaded`,
    'POST',
  );
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
