import * as Keychain from 'react-native-keychain';
import { Linking } from 'react-native';
import {
  clearPendingLink,
  loadPendingLink,
  parseDeepLink,
  PENDING_LINK_SERVICE,
  savePendingLink,
  subscribeToDeepLinks,
} from './deepLinks';

/**
 * AC-37.3: "An activation link works from both cold and warm launch."
 *
 * The cold case is the one that actually breaks in practice, and it breaks
 * silently: subscribing to the `url` event without also reading
 * `getInitialURL()` loses every link that *started* the app, which is nearly
 * all of them. So the first test here fires no event at all.
 */

jest.mock('react-native', () => ({
  Linking: {
    addEventListener: jest.fn(),
    getInitialURL: jest.fn(),
  },
}));

jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: {
    WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'AccessibleWhenUnlockedThisDeviceOnly',
  },
  setGenericPassword: jest.fn(),
  getGenericPassword: jest.fn(),
  resetGenericPassword: jest.fn(),
}));

const mockedLinking = Linking as jest.Mocked<typeof Linking>;
const mockSet = Keychain.setGenericPassword as jest.MockedFunction<
  typeof Keychain.setGenericPassword
>;
const mockGet = Keychain.getGenericPassword as jest.MockedFunction<
  typeof Keychain.getGenericPassword
>;
const mockReset = Keychain.resetGenericPassword as jest.MockedFunction<
  typeof Keychain.resetGenericPassword
>;

function installStatefulKeychainDouble(): void {
  let stored: string | null = null;
  mockSet.mockImplementation(async (_username, password) => {
    stored = password;
    return { service: PENDING_LINK_SERVICE, storage: 'keychain' } as never;
  });
  mockGet.mockImplementation(async () =>
    stored === null
      ? false
      : ({
          service: PENDING_LINK_SERVICE,
          username: 'pending-link',
          password: stored,
          storage: 'keychain',
        } as never),
  );
  mockReset.mockImplementation(async () => {
    stored = null;
    return true;
  });
}

function noEventsFrom(initialUrl: string | null): jest.Mock {
  const remove = jest.fn();
  mockedLinking.addEventListener.mockReturnValue({ remove } as never);
  mockedLinking.getInitialURL.mockResolvedValue(initialUrl);
  return remove;
}

beforeEach(() => {
  jest.clearAllMocks();
  installStatefulKeychainDouble();
});

describe('parseDeepLink', () => {
  it('reads an invitation token from the app scheme and the web link alike', () => {
    expect(parseDeepLink('damdam://invite/abc123')).toEqual({
      kind: 'invitation',
      token: 'abc123',
    });
    expect(parseDeepLink('https://damdam.app/invite/abc123')).toEqual({
      kind: 'invitation',
      token: 'abc123',
    });
  });

  it('still reads the query-string form the older messages used', () => {
    expect(parseDeepLink('damdam://invite?token=abc123')).toEqual({
      kind: 'invitation',
      token: 'abc123',
    });
  });

  it('keeps email login and recovery links purpose-bound', () => {
    expect(
      parseDeepLink('damdam://auth/email/login#token=login-token'),
    ).toEqual({ kind: 'email-login', token: 'login-token' });
    expect(
      parseDeepLink(
        'https://damdam.app/auth/email/recovery#token=recovery-token',
      ),
    ).toEqual({ kind: 'email-recovery', token: 'recovery-token' });
  });

  it('reads an eSIM activation link', () => {
    expect(parseDeepLink('damdam://esim/activate?packageId=pkg-1')).toEqual({
      kind: 'esim-activation',
      packageId: 'pkg-1',
    });
  });

  it('returns null for a link this build does not understand', () => {
    // The OS hands the app every URL registered to it. Routing an unknown one
    // somewhere arbitrary is worse than ignoring it.
    expect(parseDeepLink('damdam://something-else/1')).toBeNull();
    expect(parseDeepLink('https://example.test/invite/abc')).toBeNull();
    expect(parseDeepLink('damdam://invite')).toBeNull();
  });
});

describe('subscribeToDeepLinks', () => {
  it('delivers a link that cold-started the app, with no url event at all', async () => {
    noEventsFrom('damdam://invite/cold-token');
    const onLink = jest.fn();

    subscribeToDeepLinks(onLink);
    await flush();

    expect(onLink).toHaveBeenCalledWith({
      kind: 'invitation',
      token: 'cold-token',
    });
  });

  it('delivers a link that arrived while the app was already running', async () => {
    noEventsFrom(null);
    const onLink = jest.fn();
    subscribeToDeepLinks(onLink);
    await flush();

    const handler = mockedLinking.addEventListener.mock.calls[0][1] as (
      event: { url: string },
    ) => void;
    handler({ url: 'damdam://invite/warm-token' });
    await flush();

    expect(onLink).toHaveBeenCalledWith({
      kind: 'invitation',
      token: 'warm-token',
    });
  });

  it('persists the link before calling back, so a signed-out app keeps it', async () => {
    // The whole reason the store exists: the customer taps an invitation with
    // no session, gets sent to sign in, leaves the app to fetch the sign-in
    // mail, and comes back. Nothing in memory survives that.
    noEventsFrom('damdam://invite/persisted-token');

    subscribeToDeepLinks(() => undefined);
    await flush();

    await expect(loadPendingLink()).resolves.toEqual({
      kind: 'invitation',
      token: 'persisted-token',
    });
  });

  it('does not let an email login link overwrite the invitation it completes', async () => {
    await savePendingLink({ kind: 'invitation', token: 'invitation-token' });
    noEventsFrom('damdam://auth/email/login#token=login-token');
    const onLink = jest.fn();

    subscribeToDeepLinks(onLink);
    await flush();

    expect(onLink).toHaveBeenCalledWith({
      kind: 'email-login',
      token: 'login-token',
    });
    await expect(loadPendingLink()).resolves.toEqual({
      kind: 'invitation',
      token: 'invitation-token',
    });
  });

  it('stops calling back after unsubscribe', async () => {
    noEventsFrom(null);
    const onLink = jest.fn();
    const unsubscribe = subscribeToDeepLinks(onLink);
    const handler = mockedLinking.addEventListener.mock.calls[0][1] as (
      event: { url: string },
    ) => void;

    unsubscribe();
    handler({ url: 'damdam://invite/after-unsubscribe' });
    await flush();

    expect(onLink).not.toHaveBeenCalled();
  });

  it('filters a stale initial identity URL before persisting it again', async () => {
    noEventsFrom('damdam://auth/email/login#token=already-consumed');
    const onLink = jest.fn();

    subscribeToDeepLinks(
      onLink,
      link => link.kind !== 'email-login' && link.kind !== 'email-recovery',
    );
    await flush();

    expect(onLink).not.toHaveBeenCalled();
    await expect(loadPendingLink()).resolves.toBeNull();
  });
});

describe('the pending-link store', () => {
  it('drops a stored row whose shape this build no longer understands', async () => {
    // A build that changes the union leaves old rows behind. Half-understanding
    // one routes the customer somewhere they never asked to go.
    mockGet.mockResolvedValueOnce({
      service: PENDING_LINK_SERVICE,
      username: 'pending-link',
      password: JSON.stringify({ kind: 'invitation' }),
      storage: 'keychain',
    } as never);

    await expect(loadPendingLink()).resolves.toBeNull();
  });

  it('drops a stored row that is not JSON at all', async () => {
    mockGet.mockResolvedValueOnce({
      service: PENDING_LINK_SERVICE,
      username: 'pending-link',
      password: 'not-json',
      storage: 'keychain',
    } as never);

    await expect(loadPendingLink()).resolves.toBeNull();
  });

  it('clears on request, so a consumed link does not remain on the device', async () => {
    await savePendingLink({ kind: 'invitation', token: 'abc' });

    await clearPendingLink();

    await expect(loadPendingLink()).resolves.toBeNull();
  });

  it('stores bearer invitation tokens in platform secure storage', async () => {
    await savePendingLink({ kind: 'invitation', token: 'secret-token' });

    expect(mockSet).toHaveBeenCalledWith(
      'pending-link',
      JSON.stringify({ kind: 'invitation', token: 'secret-token' }),
      {
        service: PENDING_LINK_SERVICE,
        accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      },
    );
  });
});

function flush(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 0));
}
