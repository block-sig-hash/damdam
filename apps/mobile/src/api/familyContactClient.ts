import { API_BASE_URL } from '../config/env';
import {i18n} from '../i18n';

export type FamilyContactErrorCode =
  | 'family_contact_exists'
  | 'family_contact_not_found'
  | 'notification_unavailable'
  | 'invalid_access_token'
  | 'validation_error'
  | 'network_error';

export interface FamilyContact {
  id: string;
  phone_number: string;
  name: string | null;
  notified_of_nomination: boolean;
}

export interface FamilyContactInput {
  phone_number?: string;
  name?: string | null;
}

export class FamilyContactApiError extends Error {
  readonly code: FamilyContactErrorCode;

  constructor(code: FamilyContactErrorCode, message: string) {
    super(message);
    this.name = 'FamilyContactApiError';
    this.code = code;
  }
}

interface ErrorPayload {
  error: string;
  message: string;
}

const KNOWN_CODES: FamilyContactErrorCode[] = [
  'family_contact_exists',
  'family_contact_not_found',
  'notification_unavailable',
  'invalid_access_token',
  'validation_error',
];

async function parseError(response: Response): Promise<FamilyContactApiError> {
  try {
    const payload = (await response.json()) as ErrorPayload;
    const code = KNOWN_CODES.includes(payload.error as FamilyContactErrorCode)
      ? (payload.error as FamilyContactErrorCode)
      : 'validation_error';
    return new FamilyContactApiError(code, payload.message);
  } catch {
    return new FamilyContactApiError('network_error', i18n.t('errors.generic', {ns: 'auth'}));
  }
}

async function saveFamilyContact(
  method: 'POST' | 'PATCH',
  accessToken: string,
  input: FamilyContactInput,
): Promise<FamilyContact> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/me/family-contact`, {
      method,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(input),
    });
  } catch {
    throw new FamilyContactApiError('network_error', i18n.t('errors.network', {ns: 'auth'}));
  }

  if (!response.ok) {
    throw await parseError(response);
  }
  return (await response.json()) as FamilyContact;
}

export function nominateFamilyContact(
  accessToken: string,
  phoneNumber: string,
  name?: string,
): Promise<FamilyContact> {
  return saveFamilyContact('POST', accessToken, {
    phone_number: phoneNumber,
    ...(name === undefined ? {} : { name }),
  });
}

export function updateFamilyContact(
  accessToken: string,
  input: FamilyContactInput,
): Promise<FamilyContact> {
  return saveFamilyContact('PATCH', accessToken, input);
}
