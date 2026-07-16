import type {SOSOutboxItem} from '../services/sosOutbox';
import {API_BASE_URL} from '../config/env';

export type SOSResponse = {id: string; status: 'active' | 'cancelled' | 'resolved'};

async function request(path: string, token: string, init: RequestInit): Promise<SOSResponse> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {'Content-Type': 'application/json', Authorization: `Bearer ${token}`},
  });
  if (!response.ok) throw new Error('SOS request failed');
  return response.json() as Promise<SOSResponse>;
}

export function sendSOS(token: string, item: SOSOutboxItem): Promise<SOSResponse> {
  return request('/sos', token, {
    method: 'POST',
    body: JSON.stringify({
      client_generated_id: item.clientGeneratedId,
      timestamp: item.timestamp,
      ...(item.latitude === undefined ? {} : {
        latitude: item.latitude, longitude: item.longitude,
      }),
    }),
  });
}

export function cancelSOS(token: string, id: string): Promise<SOSResponse> {
  return request(`/sos/${id}/cancel`, token, {method: 'POST'});
}
