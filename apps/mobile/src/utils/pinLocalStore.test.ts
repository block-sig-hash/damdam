import * as Keychain from 'react-native-keychain';
import {
  clearLocalPinLock,
  clearPinLocally,
  getLocalPinState,
  hasPinStoredLocally,
  PIN_UNLOCK_ATTEMPT_LIMIT,
  recordFailedPinAttempt,
  savePinLocally,
  verifyPinLocally,
} from './pinLocalStore';

const TEST_USER_ID = '11111111-1111-4111-8111-111111111111';

jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'AccessibleWhenUnlockedThisDeviceOnly' },
  setGenericPassword: jest.fn(),
  getGenericPassword: jest.fn(),
  resetGenericPassword: jest.fn(),
}));

const mockSet = Keychain.setGenericPassword as jest.MockedFunction<
  typeof Keychain.setGenericPassword
>;
const mockGet = Keychain.getGenericPassword as jest.MockedFunction<
  typeof Keychain.getGenericPassword
>;
const mockReset = Keychain.resetGenericPassword as jest.MockedFunction<
  typeof Keychain.resetGenericPassword
>;

function credentialsFor(state: object) {
  return {
    service: 'com.damdam.pin-unlock',
    username: 'pin',
    password: JSON.stringify(state),
    storage: 'keychain',
  } as unknown as Keychain.UserCredentials;
}

beforeEach(() => {
  mockSet.mockReset();
  mockGet.mockReset();
  mockReset.mockReset();
});

describe('pinLocalStore', () => {
  it('saves a fresh PIN with zeroed attempts and no lock', async () => {
    mockSet.mockResolvedValue(false);
    await savePinLocally(TEST_USER_ID, '4682');

    expect(mockSet).toHaveBeenCalledWith(
      'pin',
      JSON.stringify({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null }),
      expect.objectContaining({ service: 'com.damdam.pin-unlock' }),
    );
  });

  it('reports no PIN stored when the keychain has nothing (AC-23.4 new-device case)', async () => {
    mockGet.mockResolvedValue(false);

    expect(await hasPinStoredLocally(TEST_USER_ID)).toBe(false);
    expect(await getLocalPinState(TEST_USER_ID)).toBeNull();
  });

  it('verifies a matching PIN locally and resets the failure counter (AC-02.3/AC-23.3)', async () => {
    mockGet.mockResolvedValue(
      credentialsFor({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 3, lockedUntil: null }),
    );
    mockSet.mockResolvedValue(false);

    expect(await verifyPinLocally(TEST_USER_ID, '4682')).toBe(true);
    expect(mockSet).toHaveBeenCalledWith(
      'pin',
      JSON.stringify({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null }),
      expect.anything(),
    );
  });

  it('rejects a non-matching PIN without writing anything', async () => {
    mockGet.mockResolvedValue(
      credentialsFor({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null }),
    );

    expect(await verifyPinLocally(TEST_USER_ID, '9317')).toBe(false);
    expect(mockSet).not.toHaveBeenCalled();
  });

  it('never calls fetch/any network primitive to verify (AC-23.3 has no network dependency)', async () => {
    mockGet.mockResolvedValue(
      credentialsFor({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null }),
    );
    const fetchSpy = jest.fn();
    const originalFetch = global.fetch;
    global.fetch = fetchSpy as unknown as typeof fetch;

    await verifyPinLocally(TEST_USER_ID, '4682');

    expect(fetchSpy).not.toHaveBeenCalled();
    global.fetch = originalFetch;
  });

  it('locks after the 5th failed attempt with a 30-minute deadline (AC-02.4/AC-23.5)', async () => {
    mockGet.mockResolvedValue(
      credentialsFor({
        userId: TEST_USER_ID,
        pin: '4682',
        failedAttempts: PIN_UNLOCK_ATTEMPT_LIMIT - 1,
        lockedUntil: null,
      }),
    );
    mockSet.mockResolvedValue(false);
    const before = Date.now();

    const result = await recordFailedPinAttempt(TEST_USER_ID);

    expect(result?.failedAttempts).toBe(PIN_UNLOCK_ATTEMPT_LIMIT);
    expect(result?.lockedUntil).not.toBeNull();
    const lockedUntilMs = new Date(result!.lockedUntil!).getTime();
    expect(lockedUntilMs).toBeGreaterThanOrEqual(before + 30 * 60 * 1000);
  });

  it('does not lock before the 5th failed attempt', async () => {
    mockGet.mockResolvedValue(
      credentialsFor({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 1, lockedUntil: null }),
    );
    mockSet.mockResolvedValue(false);

    const result = await recordFailedPinAttempt(TEST_USER_ID);

    expect(result?.failedAttempts).toBe(2);
    expect(result?.lockedUntil).toBeNull();
  });

  it('clears the lock after successful OTP recovery without touching the stored PIN', async () => {
    mockGet.mockResolvedValue(
      credentialsFor({
        userId: TEST_USER_ID,
        pin: '4682',
        failedAttempts: 5,
        lockedUntil: new Date(Date.now() + 1_000_000).toISOString(),
      }),
    );
    mockSet.mockResolvedValue(false);

    await clearLocalPinLock(TEST_USER_ID);

    expect(mockSet).toHaveBeenCalledWith(
      'pin',
      JSON.stringify({ userId: TEST_USER_ID, pin: '4682', failedAttempts: 0, lockedUntil: null }),
      expect.anything(),
    );
  });

  it('clears the stored PIN entirely', async () => {
    mockReset.mockResolvedValue(true);
    await clearPinLocally();
    expect(mockReset).toHaveBeenCalledWith({ service: 'com.damdam.pin-unlock' });
  });
});
