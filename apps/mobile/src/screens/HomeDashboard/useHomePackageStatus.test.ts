import AsyncStorage from '@react-native-async-storage/async-storage';
import {act, renderHook, waitFor} from '@testing-library/react-native';
import type {PackagePaymentStatus} from '../../api/paymentClient';
import {useHomePackageStatus} from './useHomePackageStatus';

const firstStatus: PackagePaymentStatus = {
  status: 'active',
  data_gb_total: 10,
  data_gb_remaining: 4.25,
  pstn_minutes_total: 90,
  pstn_minutes_remaining: 30,
};

beforeEach(async () => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  await AsyncStorage.clear();
});

afterEach(() => {
  jest.useRealTimers();
});

it('AC-17.2: refreshes both balances every 60 seconds', async () => {
  const fetchStatus = jest
    .fn<Promise<PackagePaymentStatus>, []>()
    .mockResolvedValueOnce(firstStatus)
    .mockResolvedValueOnce({
      ...firstStatus,
      data_gb_remaining: 4,
      pstn_minutes_remaining: 29,
    });
  const {result} = await renderHook(() =>
    useHomePackageStatus('token', 'package-1', fetchStatus),
  );

  await waitFor(() => expect(result.current.balances?.pstnMinutesRemaining).toBe(30));
  await act(async () => {
    await jest.advanceTimersByTimeAsync(60_000);
  });

  expect(fetchStatus).toHaveBeenCalledTimes(2);
  expect(result.current.balances).toMatchObject({
    remainingDataGb: 4,
    dataTotalGb: 10,
    pstnMinutesRemaining: 29,
    pstnMinutesTotal: 90,
  });
});

it('AC-17.3: uses purchased totals rather than the first observed remainder', async () => {
  const fetchStatus = jest.fn<Promise<PackagePaymentStatus>, []>().mockResolvedValue({
    status: 'active',
    data_gb_total: 10,
    data_gb_remaining: 1.9,
    pstn_minutes_total: 90,
    pstn_minutes_remaining: 4,
  });
  const {result} = await renderHook(() =>
    useHomePackageStatus('token', 'package-1', fetchStatus),
  );

  await waitFor(() => expect(result.current.balances).toMatchObject({
    remainingDataGb: 1.9,
    dataTotalGb: 10,
    pstnMinutesRemaining: 4,
    pstnMinutesTotal: 90,
  }));
});

it('AC-17.6: hydrates cached data and minutes and retains them when offline', async () => {
  await AsyncStorage.setItem(
    'damdam.home-package-status.package-1',
    JSON.stringify({
      remainingDataGb: 3.5,
      dataTotalGb: 10,
      pstnMinutesRemaining: 18,
      pstnMinutesTotal: 60,
      updatedAt: '2026-07-16T09:00:00.000Z',
    }),
  );
  const fetchStatus = jest.fn<Promise<PackagePaymentStatus>, []>().mockRejectedValue(
    new Error('offline'),
  );
  const {result} = await renderHook(() =>
    useHomePackageStatus('token', 'package-1', fetchStatus),
  );

  await waitFor(() => expect(result.current.balances).toMatchObject({
    remainingDataGb: 3.5,
    pstnMinutesRemaining: 18,
  }));
  expect(result.current.balances?.remainingDataGb).not.toBe(0);
  expect(result.current.balances?.pstnMinutesRemaining).not.toBe(0);
});
