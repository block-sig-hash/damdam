import { API_BASE_URL } from '../config/env';
import {i18n} from '../i18n';

export type CallType = 'pstn' | 'app_to_app';

export interface VoiceEligibility {
  allowed: boolean;
  call_type: CallType;
  destination: string | null;
  reason: 'cli_not_verified' | 'pstn_balance_exhausted' | null;
  pstn_minutes_remaining: number;
}

export interface VoiceToken {
  token: string;
  sip_username: string;
  expires_at: string;
  call_type: CallType;
  destination: string;
}

export interface CallHistoryItem {
  id: string;
  call_type: CallType;
  to_number: string | null;
  duration_seconds: number;
  pstn_minutes_charged: number;
  started_at: string;
}

export class VoiceApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'VoiceApiError';
  }
}

async function request<T>(path: string, accessToken: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new VoiceApiError(i18n.t('dial.offline', {ns: 'home'}));
  }
  if (!response.ok) {
    throw new VoiceApiError(i18n.t('dial.temporarilyUnavailable', {ns: 'home'}));
  }
  return (await response.json()) as T;
}

export function getVoiceEligibility(
  accessToken: string,
  phoneNumber: string,
): Promise<VoiceEligibility> {
  return request<VoiceEligibility>(
    `/voice/eligibility?phone_number=${encodeURIComponent(phoneNumber)}`,
    accessToken,
  );
}

export function getVoiceToken(accessToken: string, toNumber: string): Promise<VoiceToken> {
  return request<VoiceToken>('/voice/token', accessToken, {
    method: 'POST',
    body: JSON.stringify({ to_number: toNumber }),
  });
}

export async function getCallHistory(
  accessToken: string,
  limit = 20,
): Promise<CallHistoryItem[]> {
  const result = await request<{ calls: CallHistoryItem[] }>(
    `/me/calls?limit=${Math.min(limit, 20)}`,
    accessToken,
  );
  return result.calls;
}
