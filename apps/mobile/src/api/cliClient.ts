import { API_BASE_URL } from '../config/env';
import { localeHeader } from '../i18n';

/**
 * Mirrors apps/api/app/voice/caller_identity_service.py's CallerIdentityError
 * codes and their HTTP mapping in apps/api/app/main.py's
 * caller_identity_error_handler. See docs/api-spec.md §7.5's
 * CLI-verification amendment.
 */
export type CliErrorCode =
  | 'invalid_phone_number'
  | 'phone_verification_unavailable'
  | 'cli_verification_rate_limited'
  | 'caller_identity_not_found'
  | 'invalid_state'
  | 'verification_code_invalid'
  | 'number_already_verified_elsewhere'
  | 'no_active_caller_id'
  | 'network_error';

export type CliIdentityStatus =
  | 'unverified'
  | 'phone_verification_pending'
  | 'phone_verified'
  | 'identity_verification_pending'
  | 'identity_verified'
  | 'consent_required'
  | 'active'
  | 'suspended'
  | 'expired'
  | 'revoked';

export interface VerifiedCallerIdentity {
  id: string;
  phone_number: string;
  status: CliIdentityStatus;
  phone_verification_status: string;
  consent_version: string | null;
  consent_at: string | null;
  created_at: string;
  updated_at: string;
}

export class CliApiError extends Error {
  readonly code: CliErrorCode;

  constructor(code: CliErrorCode, message: string) {
    super(message);
    this.name = 'CliApiError';
    this.code = code;
  }
}

interface ErrorPayload {
  error: string;
  message: string;
}

const KNOWN_CODES: CliErrorCode[] = [
  'invalid_phone_number',
  'phone_verification_unavailable',
  'cli_verification_rate_limited',
  'caller_identity_not_found',
  'invalid_state',
  'verification_code_invalid',
  'number_already_verified_elsewhere',
  'no_active_caller_id',
];

async function parseErrorResponse(response: Response): Promise<CliApiError> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    const code = KNOWN_CODES.includes(payload.error as CliErrorCode)
      ? (payload.error as CliErrorCode)
      : 'network_error';
    return new CliApiError(code, payload.message);
  } catch {
    return new CliApiError('network_error', 'Something went wrong. Please try again.');
  }
}

async function request<T>(
  path: string,
  accessToken: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...localeHeader(),
        ...init?.headers,
      },
    });
  } catch {
    throw new CliApiError('network_error', 'Check your connection and try again.');
  }
  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export function startCliVerification(
  accessToken: string,
  phoneNumber: string,
): Promise<VerifiedCallerIdentity> {
  return request<VerifiedCallerIdentity>('/voice/cli/verify', accessToken, {
    method: 'POST',
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
}

export function confirmCliVerification(
  accessToken: string,
  identityId: string,
  code: string,
): Promise<VerifiedCallerIdentity> {
  return request<VerifiedCallerIdentity>(
    `/voice/cli/${identityId}/confirm`,
    accessToken,
    { method: 'POST', body: JSON.stringify({ code }) },
  );
}

export function captureCliConsent(
  accessToken: string,
  identityId: string,
  consentVersion: string,
  deviceSessionId?: string,
): Promise<VerifiedCallerIdentity> {
  return request<VerifiedCallerIdentity>(
    `/voice/cli/${identityId}/consent`,
    accessToken,
    {
      method: 'POST',
      body: JSON.stringify({
        consent_version: consentVersion,
        device_session_id: deviceSessionId,
      }),
    },
  );
}

export function revokeCli(accessToken: string): Promise<void> {
  return request<void>('/voice/cli/revoke', accessToken, { method: 'POST' });
}

export function reportCliLostSim(accessToken: string): Promise<void> {
  return request<void>('/voice/cli/lost-sim', accessToken, { method: 'POST' });
}

export function getCliStatus(
  accessToken: string,
): Promise<VerifiedCallerIdentity | null> {
  return request<VerifiedCallerIdentity | null>('/voice/cli/status', accessToken);
}
