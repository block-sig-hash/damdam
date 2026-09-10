import AsyncStorage from '@react-native-async-storage/async-storage';
import { Linking } from 'react-native';

/**
 * Deep links that survive authentication (US-37 AC-37.3).
 *
 * The hard part is not parsing. It is that the link almost never arrives at a
 * moment when it can be acted on. Someone taps an invitation in their mail on a
 * phone with no session; the app cold-starts into sign-in; they check the same
 * mailbox for the sign-in link, come back — and the intent has to still be
 * there. So a parsed link is **persisted**, not held in memory, and it is
 * cleared only when it has been consumed or explicitly dismissed.
 *
 * Why AsyncStorage and not the Keychain that holds the session: an invitation
 * token is a bearer credential, but it is one the customer just received in
 * plaintext by mail, it expires, and it grants a membership only to an account
 * that has *proved* the invited address. Keychain access is gated on device
 * unlock, and a pending link that cannot be read until the next unlock is a
 * pending link that gets lost. `clearPendingLink` on sign-out is what keeps it
 * from outliving the person who opened it.
 */

export const PENDING_LINK_KEY = 'damdam.pendingDeepLink.v1';

/** `damdam://` for the app's own scheme; https for the mailed universal links. */
const APP_SCHEME = 'damdam://';
const WEB_PREFIXES = ['https://damdam.app/', 'https://www.damdam.app/'];

export type PendingLink =
  | { kind: 'invitation'; token: string }
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
  const [route, query] = path.split('?');
  const params = new URLSearchParams(query ?? '');
  const segments = route.split('/').filter(Boolean);

  if (segments[0] === 'invite') {
    // Both shapes are in the wild: the mailed link carries the token as a path
    // segment, and the older WhatsApp message carried it as `?token=`.
    const token = segments[1] ?? params.get('token');
    return token ? { kind: 'invitation', token } : null;
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
  await AsyncStorage.setItem(PENDING_LINK_KEY, JSON.stringify(link));
}

export async function loadPendingLink(): Promise<PendingLink | null> {
  try {
    const raw = await AsyncStorage.getItem(PENDING_LINK_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as PendingLink;
    // Re-validate rather than trusting the shape: a build that changes the
    // union leaves old rows on disk, and a half-understood intent routes
    // somewhere the customer did not ask to go.
    if (parsed.kind === 'invitation' && typeof parsed.token === 'string') {
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
  await AsyncStorage.removeItem(PENDING_LINK_KEY);
}

/**
 * Cold *and* warm launch, in one subscription.
 *
 * `getInitialURL` answers the cold case — the app was not running and the OS
 * started it with a URL — and the `url` event answers the warm one. Both are
 * needed: subscribing without reading the initial URL loses every link that
 * launched the app, which is most of them.
 *
 * Every link is persisted before the callback runs, so an intent that arrives
 * while the app is signed out is still on disk when it signs in.
 */
export function subscribeToDeepLinks(
  onLink: (link: PendingLink) => void,
): () => void {
  let active = true;

  const handle = ({ url }: { url: string }) => {
    const link = parseDeepLink(url);
    if (!link) {
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
