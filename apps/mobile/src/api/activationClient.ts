import { API_BASE_URL } from '../config/env';
import {i18n} from '../i18n';

export type ActivationErrorCode =
  | 'activation_code_invalid'
  | 'activation_code_already_used'
  | 'activation_code_expired'
  | 'activation_code_phone_mismatch'
  | 'invalid_access_token'
  | 'validation_error'
  | 'network_error';

export interface ActivationPreview {
  valid: boolean;
  reason: 'activation_code_already_used' | 'activation_code_expired' | null;
  organization_name: string | null;
  pricing_tier_name: string | null;
}

export interface ActivationRedemption {
  package_id: string;
  pricing_tier_name: string;
  data_gb_total: number;
  pstn_minutes_total: number;
  status: string;
}

export class ActivationApiError extends Error {
  readonly code: ActivationErrorCode;

  constructor(code: ActivationErrorCode, message: string) {
    super(message);
    this.name = 'ActivationApiError';
    this.code = code;
  }
}

interface ErrorPayload {
  error: string;
  message: string;
}

const KNOWN_CODES: ActivationErrorCode[] = [
  'activation_code_invalid',
  'activation_code_already_used',
  'activation_code_expired',
  'activation_code_phone_mismatch',
  'invalid_access_token',
  'validation_error',
];

async function parseErrorResponse(response: Response): Promise<ActivationApiError> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    const code = KNOWN_CODES.includes(payload.error as ActivationErrorCode)
      ? (payload.error as ActivationErrorCode)
      : 'validation_error';
    const key =
      code === 'activation_code_already_used' ? 'activationUsed'
      : code === 'activation_code_expired' ? 'activationExpired'
      : code === 'activation_code_invalid' ? 'activationInvalid'
      : 'generic';
    return new ActivationApiError(code, i18n.t(`errors.${key}`, {ns: 'auth'}));
  } catch {
    return new ActivationApiError(
      'network_error',
      i18n.t('errors.generic', {ns: 'auth'}),
    );
  }
}

export async function previewActivationCode(
  activationCode: string,
): Promise<ActivationPreview> {
  let response: Response;
  try {
    response = await fetch(
      `${API_BASE_URL}/activation/${encodeURIComponent(activationCode)}`,
    );
  } catch {
    throw new ActivationApiError(
      'network_error',
      i18n.t('errors.network', {ns: 'auth'}),
    );
  }

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as ActivationPreview;
}

export async function redeemActivationCode(
  accessToken: string,
  activationCode: string,
): Promise<ActivationRedemption> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/me/activation/redeem`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ activation_code: activationCode }),
    });
  } catch {
    throw new ActivationApiError(
      'network_error',
      i18n.t('errors.network', {ns: 'auth'}),
    );
  }

  if (!response.ok) {
    throw await parseErrorResponse(response);
  }
  return (await response.json()) as ActivationRedemption;
}
