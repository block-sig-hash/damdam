import { API_BASE_URL } from '../config/env';

export interface EmergencyContact {
  hto_operator_name: string | null;
  hto_operator_phone_number: string | null;
}

export class EmergencyContactApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'EmergencyContactApiError';
  }
}

export async function getEmergencyContact(accessToken: string): Promise<EmergencyContact> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/me/emergency-contact`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch {
    throw new EmergencyContactApiError('Check your connection and try again.');
  }
  if (!response.ok) {
    throw new EmergencyContactApiError('Could not load emergency contact info.');
  }
  return response.json() as Promise<EmergencyContact>;
}
