/**
 * US-29 — device-persisted state must belong to an account, not a device.
 *
 * The defect these tests describe is live today: `pinLocalStore` writes a PIN
 * to a device-wide Keychain service with no account attached, and no code path
 * ever clears it. So when A's session ends and B signs in on the same handset,
 * B's unlock screen validates against A's PIN, and A's failed-attempt lockout
 * applies to B.
 *
 * This is the same shape of defect chunk 04A found in the offline queues: state
 * scoped to a device rather than to the account that created it.
 */

import * as Keychain from 'react-native-keychain';

import {
  clearAccountScopedState,
  getLocalPinState,
  hasPinStoredLocally,
  recordFailedPinAttempt,
  savePinLocally,
  verifyPinLocally,
} from './pinLocalStore';

jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: {
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'AccessibleWhenUnlockedThisDeviceOnly',
  },
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

const A = 'aaaaaaaa-0000-4000-8000-000000000001';
const B = 'bbbbbbbb-0000-4000-8000-000000000002';

/** A tiny in-memory Keychain, so these tests exercise the real read/write path. */
function useFakeKeychain() {
  let stored: string | null = null;
  mockSet.mockReset();
  mockGet.mockReset();
  mockReset.mockReset();
  mockSet.mockImplementation(async (_user, password) => {
    stored = password as string;
    return true as never;
  });
  mockGet.mockImplementation(async () =>
    stored === null
      ? (false as never)
      : ({
          service: 'com.damdam.pin-unlock',
          username: 'pin',
          password: stored,
          storage: 'keychain',
        } as never),
  );
  mockReset.mockImplementation(async () => {
    stored = null;
    return true as never;
  });
}

beforeEach(() => {
  useFakeKeychain();
});

describe('a PIN belongs to the account that set it', () => {
  it("does not accept account A's PIN for account B", async () => {
    await savePinLocally(A, '1234');

    await expect(verifyPinLocally(B, '1234')).resolves.toBe(false);
  });

  it('reports no stored PIN for a different account', async () => {
    await savePinLocally(A, '1234');

    await expect(hasPinStoredLocally(B)).resolves.toBe(false);
    await expect(hasPinStoredLocally(A)).resolves.toBe(true);
  });

  it('returns no local state for a different account', async () => {
    await savePinLocally(A, '1234');

    await expect(getLocalPinState(B)).resolves.toBeNull();
  });

  it("does not apply A's lockout to B", async () => {
    await savePinLocally(A, '1234');
    for (let i = 0; i < 5; i += 1) {
      await recordFailedPinAttempt(A);
    }
    const locked = await getLocalPinState(A);
    expect(locked?.lockedUntil).not.toBeNull();

    await expect(getLocalPinState(B)).resolves.toBeNull();
  });

  it('still verifies correctly for the owning account', async () => {
    await savePinLocally(A, '1234');

    await expect(verifyPinLocally(A, '1234')).resolves.toBe(true);
    await expect(verifyPinLocally(A, '9999')).resolves.toBe(false);
  });
});

describe('ending a session clears account-scoped state', () => {
  it('removes the stored PIN so the next account starts clean', async () => {
    await savePinLocally(A, '1234');

    await clearAccountScopedState();

    await expect(hasPinStoredLocally(A)).resolves.toBe(false);
    await expect(getLocalPinState(A)).resolves.toBeNull();
  });

  it('is safe to call when nothing is stored', async () => {
    await expect(clearAccountScopedState()).resolves.toBeUndefined();
  });

  it('does not strand logout when secure storage cannot be cleared', async () => {
    mockReset.mockRejectedValueOnce(new Error('keychain unavailable'));
    await expect(clearAccountScopedState()).resolves.toBeUndefined();
  });
});
