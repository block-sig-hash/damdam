import * as Keychain from 'react-native-keychain';
import {
  clearSession,
  isSessionExpired,
  loadSession,
  PersistedSession,
  saveSession,
  SESSION_INACTIVITY_LIMIT_MS,
  touchSession,
} from './sessionStore';

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
    service: 'com.damdam.session',
    username: 'session',
    password: JSON.stringify(state),
    storage: 'keychain',
  } as unknown as Keychain.UserCredentials;
}

const BASE: Omit<PersistedSession, 'lastActiveAt'> = {
  accessToken: 'access-1',
  refreshToken: 'refresh-1',
  phoneNumber: '08012345678',
  departureDate: '2026-08-01',
  packageId: 'package-1',
};

beforeEach(() => {
  mockSet.mockReset();
  mockGet.mockReset();
  mockReset.mockReset();
  mockSet.mockResolvedValue(false as unknown as Keychain.Result);
});

describe('sessionStore persistence (AC-23.1)', () => {
  it('saves a fresh session to the Keychain-backed store, not AsyncStorage', async () => {
    const saved = await saveSession(BASE);

    expect(mockSet).toHaveBeenCalledWith(
      'session',
      expect.any(String),
      expect.objectContaining({
        service: 'com.damdam.session',
        accessible: 'AccessibleWhenUnlockedThisDeviceOnly',
      }),
    );
    const written = JSON.parse(mockSet.mock.calls[0][1] as string);
    expect(written).toMatchObject(BASE);
    expect(typeof written.lastActiveAt).toBe('string');
    expect(saved.lastActiveAt).toBe(written.lastActiveAt);
  });

  it('loads a previously saved session back out', async () => {
    const persisted: PersistedSession = { ...BASE, lastActiveAt: '2026-07-01T00:00:00.000Z' };
    mockGet.mockResolvedValue(credentialsFor(persisted));

    const loaded = await loadSession();

    expect(loaded).toEqual(persisted);
  });

  it('reports no session when the Keychain has nothing', async () => {
    mockGet.mockResolvedValue(false);
    expect(await loadSession()).toBeNull();
  });

  it('clears the persisted session entirely', async () => {
    mockReset.mockResolvedValue(true);
    await clearSession();
    expect(mockReset).toHaveBeenCalledWith({ service: 'com.damdam.session' });
  });

  it('touchSession merges a patch and stamps a fresh lastActiveAt', async () => {
    const persisted: PersistedSession = { ...BASE, lastActiveAt: '2026-01-01T00:00:00.000Z' };
    mockGet.mockResolvedValue(credentialsFor(persisted));

    const result = await touchSession({ accessToken: 'access-2', refreshToken: 'refresh-2' });

    expect(result?.accessToken).toBe('access-2');
    expect(result?.refreshToken).toBe('refresh-2');
    expect(result?.phoneNumber).toBe(BASE.phoneNumber);
    expect(new Date(result!.lastActiveAt).getTime()).toBeGreaterThan(
      new Date('2026-01-01T00:00:00.000Z').getTime(),
    );
  });

  it('touchSession is a no-op returning null when nothing is persisted', async () => {
    mockGet.mockResolvedValue(false);
    expect(await touchSession()).toBeNull();
    expect(mockSet).not.toHaveBeenCalled();
  });
});

describe('isSessionExpired 30-day inactivity boundary (AC-23.2/AC-23.4)', () => {
  const NOW = new Date('2026-07-20T12:00:00.000Z').getTime();

  it('is not expired just under 30 days of inactivity', () => {
    const lastActiveAt = new Date(NOW - SESSION_INACTIVITY_LIMIT_MS + 1000).toISOString();
    expect(isSessionExpired(lastActiveAt, NOW)).toBe(false);
  });

  it('is expired at exactly 30 days of inactivity (inclusive cutoff)', () => {
    const lastActiveAt = new Date(NOW - SESSION_INACTIVITY_LIMIT_MS).toISOString();
    expect(isSessionExpired(lastActiveAt, NOW)).toBe(true);
  });

  it('is expired just over 30 days of inactivity', () => {
    const lastActiveAt = new Date(NOW - SESSION_INACTIVITY_LIMIT_MS - 1000).toISOString();
    expect(isSessionExpired(lastActiveAt, NOW)).toBe(true);
  });

  it('is not expired for a session active moments ago', () => {
    expect(isSessionExpired(new Date(NOW - 5000).toISOString(), NOW)).toBe(false);
  });
});
