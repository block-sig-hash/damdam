import * as Keychain from 'react-native-keychain';
import { AppState } from 'react-native';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import { refreshSession } from '../api/authClient';
import { SESSION_INACTIVITY_LIMIT_MS } from '../services/sessionStore';
import { shouldRequirePinAfterBackground, useSessionGate } from './useSessionGate';

/**
 * Integration coverage in the same spirit as
 * screens/PinUnlock/pinUnlockPersistence.integration.test.ts: only
 * react-native-keychain is faked, as a stateful in-memory double
 * standing in for the real Keychain/Keystore, so saveSession/
 * loadSession/touchSession/isSessionExpired all run for real and a
 * "restart" genuinely means a fresh hook instance reading only what
 * that double still has stored.
 */
jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'AccessibleWhenUnlockedThisDeviceOnly' },
  setGenericPassword: jest.fn(),
  getGenericPassword: jest.fn(),
  resetGenericPassword: jest.fn(),
}));

jest.mock('../api/authClient', () => ({
  ...jest.requireActual('../api/authClient'),
  refreshSession: jest.fn(),
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
const mockAddEventListener = AppState.addEventListener as jest.Mock;
const mockRefreshSession = refreshSession as jest.MockedFunction<typeof refreshSession>;

function installStatefulKeychainDouble() {
  let stored: string | null = null;
  mockSet.mockImplementation(async (_username, password) => {
    stored = password;
    return { service: 'com.damdam.session', storage: 'keychain' } as never;
  });
  mockGet.mockImplementation(async () => {
    if (stored === null) {
      return false;
    }
    return {
      service: 'com.damdam.session',
      username: 'session',
      password: stored,
      storage: 'keychain',
    } as never;
  });
  mockReset.mockImplementation(async () => {
    stored = null;
    return true;
  });
}

function latestAppStateHandler(): (status: string) => void {
  const call = mockAddEventListener.mock.calls[mockAddEventListener.mock.calls.length - 1];
  return call[1];
}

const BASE_SESSION = {
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
  mockAddEventListener.mockReset();
  mockAddEventListener.mockReturnValue({ remove: jest.fn() });
  mockRefreshSession.mockReset();
  installStatefulKeychainDouble();
});

describe('useSessionGate boot sequence', () => {
  it('goes straight to onboarding with no persisted session', async () => {
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).not.toBe('loading'));
    expect(result.current.phase).toBe('onboarding');
    expect(result.current.session).toBeNull();
  });

  it('persists a session on onboarding handoff and restores it across a simulated app restart (AC-23.1)', async () => {
    const { result, unmount } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).toBe('onboarding'));

    await act(async () => {
      await result.current.onOnboarded(BASE_SESSION);
    });
    expect(result.current.phase).toBe('authenticated');
    expect(result.current.session).toEqual(BASE_SESSION);

    // "Kill the app": discard all in-memory hook state. Only the
    // stateful Keychain double survives, exactly like a real restart.
    await act(async () => {
      unmount();
    });

    const { result: restarted } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(restarted.current.phase).not.toBe('loading'));

    // A cold start with a still-valid session always re-gates on PIN
    // (Screen 31's own "app-open gate" framing), but the underlying
    // tokens were genuinely recovered from secure storage, not re-typed.
    expect(restarted.current.phase).toBe('pin-gate');
    expect(restarted.current.session?.accessToken).toBe('access-1');
    expect(restarted.current.session?.refreshToken).toBe('refresh-1');
    expect(restarted.current.session?.phoneNumber).toBe('08012345678');
  });
});

describe('30-day inactivity boundary at boot (AC-23.2/AC-23.4)', () => {
  async function bootWithLastActive(lastActiveAt: string) {
    mockGet.mockResolvedValue({
      service: 'com.damdam.session',
      username: 'session',
      password: JSON.stringify({ ...BASE_SESSION, lastActiveAt }),
      storage: 'keychain',
    } as never);
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).not.toBe('loading'));
    return result;
  }

  it('restores the session just under the 30-day cutoff', async () => {
    const lastActiveAt = new Date(Date.now() - SESSION_INACTIVITY_LIMIT_MS + 60_000).toISOString();
    const result = await bootWithLastActive(lastActiveAt);
    expect(result.current.phase).toBe('pin-gate');
    expect(result.current.session).not.toBeNull();
  });

  it('forces re-authentication at exactly the 30-day cutoff (inclusive)', async () => {
    const lastActiveAt = new Date(Date.now() - SESSION_INACTIVITY_LIMIT_MS).toISOString();
    const result = await bootWithLastActive(lastActiveAt);
    expect(result.current.phase).toBe('onboarding');
    expect(result.current.session).toBeNull();
    expect(mockReset).toHaveBeenCalled();
  });

  it('forces re-authentication just over the 30-day cutoff', async () => {
    const lastActiveAt = new Date(Date.now() - SESSION_INACTIVITY_LIMIT_MS - 60_000).toISOString();
    const result = await bootWithLastActive(lastActiveAt);
    expect(result.current.phase).toBe('onboarding');
    expect(result.current.session).toBeNull();
  });
});

describe('shouldRequirePinAfterBackground pure boundary (AC-23.3)', () => {
  it('does not require PIN just under the 5-minute threshold', () => {
    expect(shouldRequirePinAfterBackground(5 * 60 * 1000 - 1)).toBe(false);
  });

  it('requires PIN at exactly the 5-minute threshold', () => {
    expect(shouldRequirePinAfterBackground(5 * 60 * 1000)).toBe(true);
  });

  it('requires PIN well over the 5-minute threshold', () => {
    expect(shouldRequirePinAfterBackground(6 * 60 * 1000)).toBe(true);
  });
});

describe('background/foreground PIN gating end-to-end (AC-23.3)', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  async function bootAuthenticated() {
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).toBe('onboarding'));
    await act(async () => {
      await result.current.onOnboarded(BASE_SESSION);
    });
    expect(result.current.phase).toBe('authenticated');
    return result;
  }

  it('a short background (under threshold) does not re-trigger the PIN gate', async () => {
    mockRefreshSession.mockResolvedValue({ access_token: 'a', refresh_token: 'b' });
    const result = await bootAuthenticated();
    const handler = latestAppStateHandler();

    await act(async () => {
      handler('background');
    });
    jest.setSystemTime(Date.now() + 60_000); // 1 minute, under the 5-minute AC-23.3 threshold
    await act(async () => {
      handler('active');
      await Promise.resolve();
    });

    expect(result.current.phase).toBe('authenticated');
  });

  it('a background at exactly the 5-minute threshold re-triggers the PIN gate without dropping tokens', async () => {
    const result = await bootAuthenticated();
    const handler = latestAppStateHandler();

    await act(async () => {
      handler('background');
    });
    jest.setSystemTime(Date.now() + 5 * 60 * 1000);
    await act(async () => {
      handler('active');
      await Promise.resolve();
    });

    expect(result.current.phase).toBe('pin-gate');
    expect(result.current.session?.accessToken).toBe('access-1');
  });

  it('a long background (well over threshold) re-triggers the PIN gate', async () => {
    const result = await bootAuthenticated();
    const handler = latestAppStateHandler();

    await act(async () => {
      handler('background');
    });
    jest.setSystemTime(Date.now() + 20 * 60 * 1000);
    await act(async () => {
      handler('active');
      await Promise.resolve();
    });

    expect(result.current.phase).toBe('pin-gate');
  });

  it('a background spanning past the 30-day cutoff clears the session entirely rather than just PIN-gating', async () => {
    const result = await bootAuthenticated();
    const handler = latestAppStateHandler();

    await act(async () => {
      handler('background');
    });
    jest.setSystemTime(Date.now() + SESSION_INACTIVITY_LIMIT_MS + 1000);
    await act(async () => {
      handler('active');
      await Promise.resolve();
    });

    expect(result.current.phase).toBe('onboarding');
    expect(result.current.session).toBeNull();
  });
});

describe('onPinUnlocked (AC-23.2 refresh-on-resume, AC-23.4 recovery)', () => {
  it('touches lastActiveAt and refreshes the access token on a routine correct-PIN unlock', async () => {
    mockRefreshSession.mockResolvedValue({
      access_token: 'refreshed-access',
      refresh_token: 'refreshed-refresh',
    });
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).toBe('onboarding'));
    await act(async () => {
      await result.current.onOnboarded(BASE_SESSION);
    });

    await act(async () => {
      await result.current.onPinUnlocked();
    });

    expect(result.current.phase).toBe('authenticated');
    await waitFor(() => expect(result.current.session?.accessToken).toBe('refreshed-access'));
    expect(mockRefreshSession).toHaveBeenCalledWith('refresh-1');
  });

  it('drops to onboarding when the refresh token is definitively invalid, not on a merely transient failure', async () => {
    const { OtpApiError } = jest.requireActual('../api/authClient');
    mockRefreshSession.mockRejectedValue(
      new OtpApiError('invalid_refresh_token', 'Refresh token is invalid.'),
    );
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).toBe('onboarding'));
    await act(async () => {
      await result.current.onOnboarded(BASE_SESSION);
    });

    await act(async () => {
      await result.current.onPinUnlocked();
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.phase).toBe('onboarding'));
    expect(result.current.session).toBeNull();
  });

  it('a transient refresh failure does not strand the user at the PIN gate', async () => {
    mockRefreshSession.mockRejectedValue(new Error('network down'));
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).toBe('onboarding'));
    await act(async () => {
      await result.current.onOnboarded(BASE_SESSION);
    });

    await act(async () => {
      await result.current.onPinUnlocked();
      await Promise.resolve();
    });

    expect(result.current.phase).toBe('authenticated');
    expect(result.current.session?.accessToken).toBe('access-1');
  });

  it('persists fresh tokens from an OTP-recovery unlock (AC-23.4)', async () => {
    const { result } = await renderHook(() => useSessionGate());
    await waitFor(() => expect(result.current.phase).toBe('onboarding'));
    await act(async () => {
      await result.current.onOnboarded(BASE_SESSION);
    });

    await act(async () => {
      await result.current.onPinUnlocked({
        access_token: 'recovered-access',
        refresh_token: 'recovered-refresh',
        is_new_user: false,
        user: {
          id: 'u1',
          phone_number: '08012345678',
          first_name: 'A',
          last_name: 'B',
          email: null,
          verified_cli: true,
          platform: 'android',
          status: 'active',
        },
      });
    });

    expect(result.current.phase).toBe('authenticated');
    expect(result.current.session?.accessToken).toBe('recovered-access');
    expect(result.current.session?.refreshToken).toBe('recovered-refresh');
    // packageId carries forward from the previously known session.
    expect(result.current.session?.packageId).toBe('package-1');
  });
});
