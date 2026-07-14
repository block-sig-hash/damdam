import { API_BASE_URL } from '../config/env';

export interface PricingTier {
  id: string;
  name: string;
  ngn_price: number;
  data_gb: number;
  pstn_minutes: number;
  is_group_tier: boolean;
  min_group_size?: number;
  max_group_size?: number;
  per_person_ngn_rate?: number;
}

interface PricingTierResponse {
  tiers: PricingTier[];
}

interface ErrorPayload {
  message?: string;
}

export class PricingApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PricingApiError';
  }
}

/**
 * US-08 / AC-08.6: always fetch the server's current admin-set price.
 * Deliberately no client cache or FX calculation exists in this layer.
 */
export async function getPricingTiers(): Promise<PricingTier[]> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/pricing/tiers`);
  } catch {
    throw new PricingApiError('Check your connection and try again.');
  }

  if (!response.ok) {
    try {
      const payload = (await response.json()) as ErrorPayload;
      throw new PricingApiError(
        payload.message ?? 'Package prices are unavailable. Please try again.',
      );
    } catch (error) {
      if (error instanceof PricingApiError) {
        throw error;
      }
      throw new PricingApiError('Package prices are unavailable. Please try again.');
    }
  }

  return ((await response.json()) as PricingTierResponse).tiers;
}
