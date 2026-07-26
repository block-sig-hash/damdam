import { API_BASE_URL } from '../config/env';
import {i18n, localeHeader} from '../i18n';

/**
 * Mirrors apps/api/app/auth/pin.py's PINError codes and their mapping
 * in apps/api/app/main.py's OTPError exception handler (PINError
 * subclasses OTPError, so it reuses that handler).
 */
export type PinErrorCode =
  | 'pin_too_weak'
  | 'invalid_access_token'
  | 'validation_error'
  | 'network_error';

export class PinApiError extends Error {
  readonly code: PinErrorCode;

  constructor(code: PinErrorCode, message: string) {
    super(message);
    this.name = 'PinApiError';
    this.code = code;
  }
}

interface ErrorPayload {
  error: string;
  message: string;
}

const KNOWN_CODES: PinErrorCode[] = ['pin_too_weak', 'invalid_access_token'];

async function parseError(response: Response): Promise<PinApiError> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    const code = KNOWN_CODES.includes(payload.error as PinErrorCode)
      ? (payload.error as PinErrorCode)
      : 'validation_error';
    return new PinApiError(
      code,
      i18n.t(code === 'pin_too_weak' ? 'errors.weakPin' : 'errors.generic', {ns: 'auth'}),
    );
  } catch {
    return new PinApiError('network_error', i18n.t('errors.generic', {ns: 'auth'}));
  }
}

export async function setPin(accessToken: string, pin: string): Promise<{ message: string }> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/auth/pin/set`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        ...localeHeader(),
      },
      body: JSON.stringify({ pin }),
    });
  } catch {
    throw new PinApiError('network_error', i18n.t('errors.network', {ns: 'auth'}));
  }

  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as { message: string };
}
