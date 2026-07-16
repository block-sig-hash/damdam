import {API_BASE_URL} from '../config/env';
import type {CheckInOutboxItem} from '../services/checkInOutbox';

export interface CheckInHistoryItem {
  id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
}

async function request<T>(path: string, accessToken: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(init?.body ? {'Content-Type': 'application/json'} : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`check-in request failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export async function sendCheckIn(
  accessToken: string,
  item: CheckInOutboxItem,
): Promise<void> {
  await request('/checkins', accessToken, {
    method: 'POST',
    body: JSON.stringify({
      client_generated_id: item.clientGeneratedId,
      timestamp: item.timestamp,
      ...(item.latitude === undefined
        ? {}
        : {latitude: item.latitude, longitude: item.longitude}),
    }),
  });
}

export async function getRecentCheckIns(
  accessToken: string,
): Promise<CheckInHistoryItem[]> {
  const response = await request<{checkins: CheckInHistoryItem[]}>(
    '/me/checkins?limit=10',
    accessToken,
  );
  return response.checkins;
}
