/**
 * The consumer's own session in the browser (US-48, chunk V05).
 *
 * This app already holds two other kinds of credential — `hto_access_token`
 * for an organization operator and `admin_access_token` for internal staff —
 * and the calling area must be reachable by **neither**. So a consumer gets a
 * third, separately named key, and the calling client reads only that one.
 *
 * That is the whole privilege separation, and it is deliberately structural
 * rather than a role check: there is no branch anywhere that could fall back to
 * an operator or admin token, so an internal user opening `/calls` is simply
 * signed out rather than authorized by accident. A role check can be widened by
 * a later edit; a token this code never reads cannot be.
 *
 * ## Why `sessionStorage`, not `localStorage`
 *
 * The other two use `localStorage`, which survives a closed browser. A calling
 * credential should not: the assignment requires short-lived grants, and this
 * is the one surface in the app that can spend money in real time on a shared
 * or public machine. `sessionStorage` is per-tab and dies with the tab, which
 * also means a second tab starts signed out rather than inheriting a call.
 */

const ACCESS_TOKEN_KEY = "damdam_consumer_access_token";
const USER_ID_KEY = "damdam_consumer_user_id";
/** Namespaced per user, so a signed-out account leaves nothing addressable. */
const ACTIVE_CALL_PREFIX = "damdam_consumer_active_call:";

export type ConsumerSession = {
  accessToken: string;
  userId: string;
};

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // A browser with site data blocked. Calling still works for this page load;
    // it simply will not survive a refresh, which is the correct degradation.
    return null;
  }
}

export function readConsumerSession(): ConsumerSession | null {
  const store = storage();
  const accessToken = store?.getItem(ACCESS_TOKEN_KEY);
  const userId = store?.getItem(USER_ID_KEY);
  if (!accessToken || !userId) {
    return null;
  }
  return { accessToken, userId };
}

export function writeConsumerSession(session: ConsumerSession): void {
  const store = storage();
  store?.setItem(ACCESS_TOKEN_KEY, session.accessToken);
  store?.setItem(USER_ID_KEY, session.userId);
}

/**
 * Sign out, and take the scoped data with it.
 *
 * Every key this module owns is removed, including the remembered active call.
 * Leaving that behind would let the next person to use the browser reconcile
 * somebody else's call — and, because reconciliation is a real API request with
 * a real attempt id, be shown what it cost.
 */
export function clearConsumerSession(): void {
  const store = storage();
  if (!store) {
    return;
  }
  const scoped = [ACCESS_TOKEN_KEY, USER_ID_KEY];
  for (let index = 0; index < store.length; index += 1) {
    const key = store.key(index);
    if (key?.startsWith(ACTIVE_CALL_PREFIX)) {
      scoped.push(key);
    }
  }
  for (const key of scoped) {
    store.removeItem(key);
  }
}

/**
 * Remember which attempt is live, so a refresh reconciles instead of redialing.
 *
 * Keyed by user id: a different account signing into the same tab must not
 * inherit this. And it holds an **attempt id only** — never a provider token,
 * never a credential. The attempt id names something the server will re-check
 * ownership of before telling us anything about it.
 */
export function rememberActiveCall(userId: string, attemptId: string | null): void {
  const store = storage();
  if (!store) {
    return;
  }
  const key = `${ACTIVE_CALL_PREFIX}${userId}`;
  if (attemptId) {
    store.setItem(key, attemptId);
  } else {
    store.removeItem(key);
  }
}

export function readActiveCall(userId: string): string | null {
  return storage()?.getItem(`${ACTIVE_CALL_PREFIX}${userId}`) ?? null;
}
