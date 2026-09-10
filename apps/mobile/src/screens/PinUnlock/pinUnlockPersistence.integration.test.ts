import * as Keychain from 'react-native-keychain';
import { act, renderHook, waitFor } from '@testing-library/react-native';
import { savePinLocally } from '../../utils/pinLocalStore';
import { usePinUnlock } from './usePinUnlock';

const TEST_USER_ID = '11111111-1111-4111-8111-111111111111';

/**
 * Integration coverage for two claims the unit tests only prove at the
 * mocked-layer boundary: that a lock genuinely survives an app restart
 * (not just "a fresh hook instance believes whatever getLocalPinState
 * returns"), and that the real pinLocalStore + usePinUnlock chain —
 * not individually mocked pieces — actually behaves this way end to
 * end. Only react-native-keychain itself is faked here, as a stateful
 * in-memory store standing in for the OS Keychain/Keystore, so every
 * other function in the chain (savePinLocally, recordFailedPinAttempt,
 * getLocalPinState, verifyPinLocally, usePinUnlock) runs for real.
 */
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

/** A real in-memory double of the OS Keychain: writes persist across
 * calls within a test, exactly like the real thing persists across an
 * app restart — unlike per-call jest.fn() mocks, which don't. */
function installStatefulKeychainDouble() {
  let stored: string | null = null;
  mockSet.mockImplementation(async (_username, password) => {
    stored = password;
    return { service: 'com.damdam.pin-unlock', storage: 'keychain' } as never;
  });
  mockGet.mockImplementation(async () => {
    if (stored === null) {
      return false;
    }
    return {
      service: 'com.damdam.pin-unlock',
      username: 'pin',
      password: stored,
      storage: 'keychain',
    } as never;
  });
}

beforeEach(() => {
  mockSet.mockReset();
  mockGet.mockReset();
  installStatefulKeychainDouble();
});

describe('PIN Unlock persistence (real pinLocalStore + usePinUnlock, faked Keychain only)', () => {
  it('a 30-minute lock genuinely survives what an app restart looks like: a fresh hook instance reading the same underlying store (AC-02.4/AC-23.5)', async () => {
    // "PIN Setup" happens first, for real, writing through savePinLocally.
    await savePinLocally(TEST_USER_ID, '4682');

    // First "app session": mount usePinUnlock and fail 5 times for real,
    // through the real recordFailedPinAttempt/verifyPinLocally chain.
    const onUnlockedFirstSession = jest.fn();
    const { result: firstSession, unmount } = await renderHook(() =>
      usePinUnlock({ userId: TEST_USER_ID, onUnlocked: onUnlockedFirstSession }),
    );
    await waitFor(() => expect(firstSession.current.stage).not.toBe('checking'));
    expect(firstSession.current.stage).toBe('entry');

    for (let attempt = 0; attempt < 5; attempt += 1) {
      await act(async () => {
        firstSession.current.setValue('0000');
      });
      await act(async () => {
        await firstSession.current.submit();
        // Let useCountdownSeconds' passive effect (triggered by the
        // lockoutTotalSeconds change on the 5th failure) actually flush
        // before this act() call closes — without this, React schedules
        // that effect just after act() considers itself done, which
        // both logs "not wrapped in act()" and can corrupt later
        // tests' rendering in this same file.
        await Promise.resolve();
        await Promise.resolve();
      });
    }
    expect(firstSession.current.stage).toBe('locked');
    expect(onUnlockedFirstSession).not.toHaveBeenCalled();

    // "Kill the app": unmount, discarding every bit of in-memory React
    // state usePinUnlock was holding — only what's in the (stateful)
    // Keychain double survives, exactly like a real app restart.
    await act(async () => {
      unmount();
    });

    // "Reopen the app": a brand-new hook instance, no shared JS state
    // with the first one at all — it can only know about the lock if
    // pinLocalStore genuinely persisted the deadline.
    const onUnlockedSecondSession = jest.fn();
    const { result: secondSession, unmount: unmountSecond } = await renderHook(() =>
      usePinUnlock({ userId: TEST_USER_ID, onUnlocked: onUnlockedSecondSession }),
    );
    await waitFor(() => expect(secondSession.current.stage).not.toBe('checking'));

    expect(secondSession.current.stage).toBe('locked');
    expect(secondSession.current.lockoutSecondsRemaining).toBeGreaterThan(29 * 60);
    expect(secondSession.current.lockoutSecondsRemaining).toBeLessThanOrEqual(30 * 60);

    // The correct PIN still doesn't work while genuinely locked, even
    // in this fresh session — the lock isn't just a UI-only flag.
    await act(async () => {
      secondSession.current.setValue('4682');
    });
    await act(async () => {
      await secondSession.current.submit();
    });
    expect(onUnlockedSecondSession).not.toHaveBeenCalled();

    // Clear the 'locked' stage's real setInterval (useCountdownSeconds)
    // before the next test — an un-cleared 30-minute countdown interval
    // left running with real timers would otherwise keep firing in the
    // background and can corrupt later tests' rendering in this file.
    await act(async () => {
      unmountSecond();
    });
  });

  it('routes to recovery on a genuinely fresh device — no savePinLocally call ever made (AC-23.4)', async () => {
    // No savePinLocally call at all: this is what a brand-new device
    // (or one that never finished PIN Setup) actually looks like —
    // not a mocked "return null" stand-in for that state.
    const onUnlocked = jest.fn();
    const { result } = await renderHook(() => usePinUnlock({ userId: TEST_USER_ID, onUnlocked }));

    await waitFor(() => expect(result.current.stage).not.toBe('checking'));

    expect(result.current.stage).toBe('no-local-pin');
    expect(mockGet).toHaveBeenCalled();
  });

  it('a correct PIN unlocks for real end-to-end, no network involved', async () => {
    await savePinLocally(TEST_USER_ID, '9317');
    const onUnlocked = jest.fn();
    const { result } = await renderHook(() => usePinUnlock({ userId: TEST_USER_ID, onUnlocked }));
    await waitFor(() => expect(result.current.stage).not.toBe('checking'));
    expect(result.current.stage).toBe('entry');

    const fetchSpy = jest.fn();
    const originalFetch = global.fetch;
    global.fetch = fetchSpy as unknown as typeof fetch;

    await act(async () => {
      result.current.setValue('9317');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(onUnlocked).toHaveBeenCalledWith();
    expect(fetchSpy).not.toHaveBeenCalled();
    global.fetch = originalFetch;
  });
});
