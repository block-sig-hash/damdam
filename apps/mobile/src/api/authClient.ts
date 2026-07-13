import { API_BASE_URL } from '../config/env';

/**
 * Mirrors apps/api/app/auth/schemas.py and the error codes raised by
 * apps/api/app/otp/service.py, mapped to HTTP statuses in
 * apps/api/app/main.py's OTPError exception handler.
 */
export type Platform = 'ios' | 'android';

export type OtpErrorCode =
  | 'account_exists'
  | 'rate_limited'
  | 'otp_unavailable'
  | 'invalid_otp'
  | 'otp_expired'
  | 'locked'
  | 'validation_error'
  | 'network_error';

export interface UserResponse {
  id: string;
  phone_number: string;
  first_name: string;
  last_name: string;
  email: string | null;
  verified_cli: boolean;
  platform: string;
  status: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user: UserResponse;
  is_new_user: boolean;
}

export class OtpApiError extends Error {
  readonly code: OtpErrorCode;
  readonly retryAfter?: number;

  constructor(code: OtpErrorCode, message: string, retryAfter?: number) {
    super(message);
    this.name = 'OtpApiError';
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

interface ErrorPayload {
  error: string;
  message: string;
  details?: { retry_after?: number };
}

const KNOWN_CODES: OtpErrorCode[] = [
  'account_exists',
  'rate_limited',
  'otp_unavailable',
  'invalid_otp',
  'otp_expired',
  'locked',
  'validation_error',
];

async function parseErrorResponse(response: Response): Promise<OtpApiError> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    const code = KNOWN_CODES.includes(payload.error as OtpErrorCode)
      ? (payload.error as OtpErrorCode)
      : 'validation_error';
    return new OtpApiError(code, payload.message, payload.details?.retry_after);
  } catch {
    return new OtpApiError('network_error', 'Something went wrong. Please try again.');
  }
}

async function post<TResponse>(path: string, body: unknown): Promise<TResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new OtpApiError('network_error', 'Check your connection and try again.');
  }

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }

  return (await response.json()) as TResponse;
}

export function requestOtp(phoneNumber: string): Promise<{ message: string }> {
  return post('/auth/otp/request', { phone_number: phoneNumber });
}

export function verifyOtp(
  phoneNumber: string,
  otp: string,
  platform: Platform,
): Promise<AuthResponse> {
  return post('/auth/otp/verify', { phone_number: phoneNumber, otp, platform });
}
