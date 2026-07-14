import { useCallback, useEffect, useState } from 'react';
import {
  getPricingTiers,
  PricingApiError,
  PricingTier,
} from '../../api/pricingClient';

type PackageTierStatus = 'loading' | 'ready' | 'error';

interface UsePackageTiersResult {
  status: PackageTierStatus;
  tiers: PricingTier[];
  errorMessage: string | null;
  retry: () => Promise<void>;
}

export function usePackageTiers(): UsePackageTiersResult {
  const [status, setStatus] = useState<PackageTierStatus>('loading');
  const [tiers, setTiers] = useState<PricingTier[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus('loading');
    setErrorMessage(null);
    try {
      const currentTiers = await getPricingTiers();
      const names = new Set(currentTiers.map((tier) => tier.name));
      if (
        !['Starter', 'Basic', 'Standard', 'Family'].every((name) =>
          names.has(name),
        )
      ) {
        throw new PricingApiError(
          'Package prices are unavailable. Please try again.',
        );
      }
      setTiers(currentTiers);
      setStatus('ready');
    } catch (error) {
      setTiers([]);
      setStatus('error');
      setErrorMessage(
        error instanceof PricingApiError
          ? error.message
          : 'Package prices are unavailable. Please try again.',
      );
    }
  }, []);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  return { status, tiers, errorMessage, retry: load };
}
