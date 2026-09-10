import { act, renderHook } from '@testing-library/react-native';
import { AuthResponse } from '../../api/authClient';
import {
  clearLocalPinLock,
  getLocalPinState,
  PIN_UNLOCK_ATTEMPT_LIMIT,
  recordFailedPinAttempt,
  verifyPinLocally,
} from '../../utils/pinLocalStore';
import { usePinUnlock } from './usePinUnlock';

const TEST_USER_ID = '11111111-1111-4111-8111-111111111111';

jest.mock('../../utils/pinLocalStore', () => ({
  ...jest.requireActual('../../utils/pinLocalStore'),
  getLocalPinState: jest.fn(),
  verifyPinLocally: jest.fn(),
  recordFailedPinAttempt: jest.fn(),
  clearLocalPinLock: jest.fn(),
}));

const mockGetState = getLocalPinState as jest.MockedFunction<typeof getLocalPinState>;
const mockVerify = verifyPinLocally as jest.MockedFunction<typeof verifyPinLocally>;
const mockRecordFailure = recordFailedPinAttempt as jest.MockedFunction<
  typeof recordFailedPinAttempt
>;
const mockClearLock = clearLocalPinLock as jest.MockedFunction<typeof clearLocalPinLock>;

const AUTH_RESPONSE: AuthResponse = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  is_new_user: false,
  user: {
    id: 'user-1',
    phone_number: '+2348012345678',
    first_name: '',
    last_name: '',
    email: null,
    verified_cli: true,
    locale: 'en' as const,
    platform: 'android',
    status: 'active',
  },
};

beforeEach(() => {
  jest.useFakeTimers();
  mockGetState.mockReset();
  mockVerify.mockReset();
  mockRecordFailure.mockReset();
  mockClearLock.mockReset();
});

afterEach(() => {
  jest.useRealTimers();
});

async function mount(onUnlocked: jest.Mock) {
  return renderHook(() => usePinUnlock({ userId: TEST_USER_ID, onUnlocked }));
}

describe('usePinUnlock', () => {
  it('lands on no-local-pin when nothing is stored (AC-23.4 new-device case)', async () => {
    mockGetState.mockResolvedValue(null);
    const { result } = await mount(jest.fn());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.stage).toBe('no-local-pin');
  });

  it('starts at entry when a PIN is stored and not locked', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null });
    const { result } = await mount(jest.fn());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.stage).toBe('entry');
  });

  it('resumes a still-active lock from a persisted deadline on mount', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 5,
      lockedUntil: new Date(Date.now() + 120_000).toISOString(),
    });
    const { result } = await mount(jest.fn());

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.stage).toBe('locked');
    expect(result.current.lockoutSecondsRemaining).toBeGreaterThan(0);
  });

  it('unlocks immediately with no network call on a matching PIN (AC-02.3/AC-23.3)', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null });
    mockVerify.mockResolvedValue(true);
    const onUnlocked = jest.fn();
    const { result } = await mount(onUnlocked);
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(mockVerify).toHaveBeenCalledWith(TEST_USER_ID, '4682');
    expect(onUnlocked).toHaveBeenCalledWith();
    expect(mockRecordFailure).not.toHaveBeenCalled();
  });

  it('shows the remaining-attempts count on a wrong PIN before lockout', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null });
    mockVerify.mockResolvedValue(false);
    mockRecordFailure.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 2, lockedUntil: null });
    const onUnlocked = jest.fn();
    const { result } = await mount(onUnlocked);
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      result.current.setValue('0000');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.stage).toBe('entry');
    expect(result.current.errorMessage).toBe('Incorrect PIN. 3 attempts left.');
    expect(onUnlocked).not.toHaveBeenCalled();
  });

  it('locks for 30 minutes after the 5th failed attempt (AC-02.4/AC-23.5)', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: PIN_UNLOCK_ATTEMPT_LIMIT - 1,
      lockedUntil: null,
    });
    mockVerify.mockResolvedValue(false);
    mockRecordFailure.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: PIN_UNLOCK_ATTEMPT_LIMIT,
      lockedUntil: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    });
    const { result } = await mount(jest.fn());
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      result.current.setValue('0000');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.stage).toBe('locked');
    expect(result.current.lockoutSecondsRemaining).toBe(30 * 60);
  });

  it('counts the lockout down and returns to entry once it expires', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: PIN_UNLOCK_ATTEMPT_LIMIT,
      lockedUntil: new Date(Date.now() + 5_000).toISOString(),
    });
    const { result } = await mount(jest.fn());
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.stage).toBe('locked');

    await act(async () => {
      jest.advanceTimersByTime(5_000);
    });

    expect(result.current.stage).toBe('entry');
  });

  it('unlocks via OTP recovery, clearing the local lock without changing the PIN', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: PIN_UNLOCK_ATTEMPT_LIMIT,
      lockedUntil: new Date(Date.now() + 120_000).toISOString(),
    });
    mockClearLock.mockResolvedValue(undefined);
    const onUnlocked = jest.fn();
    const { result } = await mount(onUnlocked);
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      result.current.startRecovery();
    });
    expect(result.current.isRecovering).toBe(true);

    await act(async () => {
      await result.current.handleRecovered(AUTH_RESPONSE);
    });

    expect(mockClearLock).toHaveBeenCalled();
    expect(result.current.isRecovering).toBe(false);
    expect(onUnlocked).toHaveBeenCalledWith(AUTH_RESPONSE);
  });

  it('lets the pilgrim cancel out of recovery back to PIN entry', async () => {
    mockGetState.mockResolvedValue({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null });
    const { result } = await mount(jest.fn());
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      result.current.startRecovery();
    });
    expect(result.current.isRecovering).toBe(true);

    await act(async () => {
      result.current.cancelRecovery();
    });
    expect(result.current.isRecovering).toBe(false);
  });
});
