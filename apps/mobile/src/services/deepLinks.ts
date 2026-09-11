import * as Keychain from 'react-native-keychain';
import { Linking } from 'react-native';

/**
 * Deep links that survive authentication (US-37 AC-37.3).
 *
 * The hard part is not parsing. It is that the link almost never arrives at a
 * moment when it can be acted on. Someone taps an invitation in their mail on a
 * phone with no session; the app cold-starts into sign-in; they check the same
 * mailbox for the sign-in link, come back — and the intent has to still be
 * there. So a deferred product link is **persisted**, not held in memory, and
 * is cleared only when consumed or explicitly dismissed. Email authentication
 * links are the exception: they are consumed immediately and must not overwrite
 * the invitation whose sign-in round trip they are completing.
 *
 * The pending intent lives in platform secure storage because an invitation
 * token is a bearer credential. `WHEN_UNLOCKED_THIS_DEVICE_ONLY` still permits
 * the cold/warm handoff after the customer unlocks and opens the app, while
 * preventing device backups or plaintext app storage from carrying the token.
 */

export const PENDING_LINK_SERVICE = 'com.damdam.pending-deep-link';

/** `damdam://` for the app's own scheme; https for the mailed universal links. */
const APP_SCHEME = 'damdam://';
const WEB_PREFIXES = ['https://damdam.app/', 'https://www.damdam.app/'];

export type PendingLink =
  | { kind: 'invitation'; token: string }
  | { kind: 'email-login'; token: string }
  | { kind: 'email-recovery'; token: string }
  | { kind: 'esim-activation'; packageId: string }
  | { kind: 'order'; orderId: string };

/**
 * Turn a URL into an intent, or null.
 *
 * Null is a normal outcome, not an error: the OS hands the app every URL
 * registered to it, including ones a later chunk will add. An unrecognized link
 * must leave the app where it was rather than routing somewhere arbitrary.
 */
export function parseDeepLink(url: string): PendingLink | null {
  const path = toPath(url);
  if (path === null) {
    return null;
  }
  const [pathAndQuery, fragment] = path.split('#');
  const [route, query] = pathAndQuery.split('?');
  const params = new URLSearchParams(query ?? fragment ?? '');
  const segments = route.split('/').filter(Boolean);

  if (segments[0] === 'invite') {
    // Both shapes are in the wild: the mailed link carries the token as a path
    // segment, and the older WhatsApp message carried it as `?token=`.
    const token = segments[1] ?? params.get('token');
    return token ? { kind: 'invitation', token } : null;
  }
  if (segments[0] === 'auth' && segments[1] === 'email') {
    const token = segments[3] ?? params.get('token');
    if (!token) {
      return null;
    }
    if (segments[2] === 'login') {
      return { kind: 'email-login', token };
    }
    if (segments[2] === 'recovery') {
      return { kind: 'email-recovery', token };
    }
  }
  if (segments[0] === 'esim' && segments[1] === 'activate') {
    const packageId = params.get('packageId') ?? segments[2];
    return packageId ? { kind: 'esim-activation', packageId } : null;
  }
  if (segments[0] === 'orders') {
    const orderId = segments[1] ?? params.get('orderId');
    return orderId ? { kind: 'order', orderId } : null;
  }
  return null;
}

function toPath(url: string): string | null {
  if (url.startsWith(APP_SCHEME)) {
    return url.slice(APP_SCHEME.length);
  }
  const web = WEB_PREFIXES.find(prefix => url.startsWith(prefix));
  return web ? url.slice(web.length) : null;
}

export async function savePendingLink(link: PendingLink): Promise<void> {
  await Keychain.setGenericPassword('pending-link', JSON.stringify(link), {
    service: PENDING_LINK_SERVICE,
    accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
  });
}

export async function loadPendingLink(): Promise<PendingLink | null> {
  try {
    const credentials = await Keychain.getGenericPassword({
      service: PENDING_LINK_SERVICE,
    });
    if (!credentials) {
      return null;
    }
    const parsed = JSON.parse(credentials.password) as PendingLink;
    // Re-validate rather than trusting the shape: a build that changes the
    // union leaves old rows on disk, and a half-understood intent routes
    // somewhere the customer did not ask to go.
    if (parsed.kind === 'invitation' && typeof parsed.token === 'string') {
      return parsed;
    }
    if (
      (parsed.kind === 'email-login' || parsed.kind === 'email-recovery') &&
      typeof parsed.token === 'string'
    ) {
      return parsed;
    }
    if (
      parsed.kind === 'esim-activation' &&
      typeof parsed.packageId === 'string'
    ) {
      return parsed;
    }
    if (parsed.kind === 'order' && typeof parsed.orderId === 'string') {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

export async function clearPendingLink(): Promise<void> {
  await Keychain.resetGenericPassword({ service: PENDING_LINK_SERVICE });
}

/**
 * Cold *and* warm launch, in one subscription.
 *
 * `getInitialURL` answers the cold case — the app was not running and the OS
 * started it with a URL — and the `url` event answers the warm one. Both are
 * needed: subscribing without reading the initial URL loses every link that
 * launched the app, which is most of them.
 *
 * Deferred invitation/order/eSIM links are persisted before the callback runs,
 * so an intent that arrives while the app is signed out is still on disk when
 * it signs in. A one-time email authentication link is consumed immediately
 * and deliberately leaves that deferred intent untouched.
 */
export function subscribeToDeepLinks(
  onLink: (link: PendingLink) => void,
  shouldHandle: (link: PendingLink) => boolean = () => true,
): () => void {
  let active = true;

  const handle = ({ url }: { url: string }) => {
    const link = parseDeepLink(url);
    if (!link) {
      return;
    }
    // The initial URL is visible to every navigator mounted during this app
    // process. After an email link authenticates the signed-out navigator, the
    // authenticated navigator mounts and sees the same initial URL; filtering
    // before persistence prevents it from resurrecting an already-consumed
    // one-time credential.
    if (!shouldHandle(link)) {
      return;
    }
    if (link.kind === 'email-login' || link.kind === 'email-recovery') {
      if (active) {
        onLink(link);
      }
      return;
    }
    savePendingLink(link)
      .catch(() => undefined)
      .finally(() => {
        if (active) {
          onLink(link);
        }
      });
  };

  const subscription = Linking.addEventListener('url', handle);
  Linking.getInitialURL()
    .then(url => {
      if (url && active) {
        handle({ url });
      }
    })
    .catch(() => undefined);

  return () => {
    active = false;
    subscription.remove();
  };
}
