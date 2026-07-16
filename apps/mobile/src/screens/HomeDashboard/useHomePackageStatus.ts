import AsyncStorage from '@react-native-async-storage/async-storage';
import {useCallback, useEffect, useRef, useState} from 'react';
import {
  getPackageStatus,
  type PackagePaymentStatus,
} from '../../api/paymentClient';

const REFRESH_INTERVAL_MS = 60_000;
const CACHE_PREFIX = 'damdam.home-package-status.';

export interface HomePackageBalances {
  remainingDataGb: number;
  dataTotalGb: number;
  pstnMinutesRemaining: number;
  pstnMinutesTotal: number;
  updatedAt: string;
}

type StatusFetcher = (
  accessToken: string,
  packageId: string,
) => Promise<PackagePaymentStatus>;

function isCachedBalances(value: unknown): value is HomePackageBalances {
  if (!value || typeof value !== 'object') return false;
  const row = value as Partial<HomePackageBalances>;
  return (
    typeof row.remainingDataGb === 'number' &&
    typeof row.dataTotalGb === 'number' &&
    typeof row.pstnMinutesRemaining === 'number' &&
    typeof row.pstnMinutesTotal === 'number' &&
    typeof row.updatedAt === 'string'
  );
}

export function useHomePackageStatus(
  accessToken: string,
  packageId?: string,
  fetchStatus: StatusFetcher = getPackageStatus,
): {
  balances: HomePackageBalances | null;
  refresh: () => Promise<HomePackageBalances | null>;
} {
  const [balances, setBalances] = useState<HomePackageBalances | null>(null);
  const balancesRef = useRef<HomePackageBalances | null>(null);
  const packageIdRef = useRef(packageId);
  packageIdRef.current = packageId;

  const applyBalances = useCallback((next: HomePackageBalances | null) => {
    balancesRef.current = next;
    setBalances(next);
  }, []);

  const refresh = useCallback(async (): Promise<HomePackageBalances | null> => {
    if (!packageId) return null;
    const status = await fetchStatus(accessToken, packageId);
    if (packageIdRef.current !== packageId) return null;
    const next: HomePackageBalances = {
      remainingDataGb: status.data_gb_remaining,
      dataTotalGb: status.data_gb_total,
      pstnMinutesRemaining: status.pstn_minutes_remaining,
      pstnMinutesTotal: status.pstn_minutes_total,
      updatedAt: new Date().toISOString(),
    };
    applyBalances(next);
    await AsyncStorage.setItem(`${CACHE_PREFIX}${packageId}`, JSON.stringify(next)).catch(
      () => undefined,
    );
    return next;
  }, [accessToken, applyBalances, fetchStatus, packageId]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    if (!packageId) {
      applyBalances(null);
      return () => undefined;
    }
    applyBalances(null);

    const start = async (): Promise<void> => {
      try {
        const raw = await AsyncStorage.getItem(`${CACHE_PREFIX}${packageId}`);
        if (active && raw) {
          const cached: unknown = JSON.parse(raw);
          if (isCachedBalances(cached)) applyBalances(cached);
        }
      } catch {
        // A corrupt or unavailable cache must not prevent a live refresh.
      }
      if (!active) return;
      await refresh().catch(() => undefined);
      if (!active) return;
      timer = setInterval(() => {
        refresh().catch(() => undefined);
      }, REFRESH_INTERVAL_MS);
    };

    start().catch(() => undefined);
    return () => {
      active = false;
      if (timer) clearInterval(timer);
    };
  }, [applyBalances, packageId, refresh]);

  return {balances, refresh};
}
