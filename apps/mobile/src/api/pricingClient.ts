import { API_BASE_URL } from '../config/env';
import {i18n, localeHeader} from '../i18n';

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
    response = await fetch(`${API_BASE_URL}/pricing/tiers`, { headers: localeHeader() });
  } catch {
    throw new PricingApiError(i18n.t('errors.network', {ns: 'auth'}));
  }

  if (!response.ok) {
    try {
      await response.json();
      throw new PricingApiError(
        i18n.t('packages.unavailable', {ns: 'payments'}),
      );
    } catch (error) {
      if (error instanceof PricingApiError) {
        throw error;
      }
      throw new PricingApiError(i18n.t('packages.unavailable', {ns: 'payments'}));
    }
  }

  return ((await response.json()) as PricingTierResponse).tiers;
}
