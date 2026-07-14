import { act, renderHook } from '@testing-library/react-native';
import { ActivationApiError, redeemActivationCode } from '../../api/activationClient';
import { useActivationRedeem } from './useActivationRedeem';

jest.mock('../../api/activationClient', () => {
  const actual = jest.requireActual('../../api/activationClient');
  return { ...actual, redeemActivationCode: jest.fn() };
});

const mockRedeem = redeemActivationCode as jest.MockedFunction<
  typeof redeemActivationCode
>;

beforeEach(() => {
  mockRedeem.mockReset();
});

describe('useActivationRedeem', () => {
  it('redeems automatically on mount without a separate user action (AC-07.4)', async () => {
    mockRedeem.mockResolvedValue({
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    });

    const { result } = await renderHook(() =>
      useActivationRedeem({ accessToken: 'token', activationCode: 'ABCD1234' }),
    );

    expect(mockRedeem).toHaveBeenCalledWith('token', 'ABCD1234');
    expect(result.current.status).toBe('success');
    expect(result.current.result?.pricing_tier_name).toBe('Standard');
  });

  it('surfaces a failure and allows retrying', async () => {
    mockRedeem.mockRejectedValueOnce(
      new ActivationApiError('activation_code_expired', 'This code has expired.'),
    );
    const { result } = await renderHook(() =>
      useActivationRedeem({ accessToken: 'token', activationCode: 'ABCD1234' }),
    );

    expect(result.current.status).toBe('error');
    expect(result.current.errorMessage).toBe('This code has expired.');

    mockRedeem.mockResolvedValueOnce({
      package_id: 'package-1',
      pricing_tier_name: 'Standard',
      data_gb_total: 10,
      pstn_minutes_total: 60,
      status: 'active',
    });
    await act(async () => {
      await result.current.retry();
    });

    expect(mockRedeem).toHaveBeenCalledTimes(2);
    expect(result.current.status).toBe('success');
  });
});
