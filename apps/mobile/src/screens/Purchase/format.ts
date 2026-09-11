/**
 * Turning what the API sends into what a person reads (US-37, chunk 19).
 *
 * `money` is the load-bearing one. The server sends `"12000.00"` already scaled
 * to the currency, so this must not reinterpret it: parsing to a float and
 * re-formatting is how a quoted price becomes a different displayed price, and
 * the amount shown next to a pay button has to be the amount that was quoted.
 * The string is therefore passed through untouched, with the currency code in
 * front of it.
 */

export function money(amount: string, currency: string): string {
  return `${currency} ${amount}`;
}

const GIGABYTE = 1024 * 1024 * 1024;
const MEGABYTE = 1024 * 1024;

/**
 * Bytes as the customer thinks of them.
 *
 * Binary units, matching what the allowance actually is and what the usage
 * meter in chunk 16 counts down. One decimal place, so 1.5 GB does not round to
 * 2 GB on a card next to a price.
 */
export function dataAllowance(bytes: number): string | null {
  if (bytes <= 0) {
    return null;
  }
  if (bytes >= GIGABYTE) {
    return `${trimZero(bytes / GIGABYTE)} GB`;
  }
  return `${trimZero(bytes / MEGABYTE)} MB`;
}

export function voiceAllowance(seconds: number): number | null {
  return seconds > 0 ? Math.round(seconds / 60) : null;
}

function trimZero(value: number): string {
  const fixed = value.toFixed(1);
  return fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed;
}

/**
 * Whole minutes left before a quote expires, floored, never negative.
 *
 * Floored deliberately: showing "1 minute left" for 59 seconds and then failing
 * the checkout is worse than showing "less than a minute". Zero is the caller's
 * cue to render the expired state rather than a countdown.
 */
export function minutesUntil(expiresAt: string, now: number = Date.now()): number {
  const remaining = new Date(expiresAt).getTime() - now;
  if (!Number.isFinite(remaining) || remaining <= 0) {
    return 0;
  }
  return Math.floor(remaining / 60_000);
}

export function hasExpired(expiresAt: string, now: number = Date.now()): boolean {
  const at = new Date(expiresAt).getTime();
  // An unparseable timestamp is not treated as expired: refusing a quote the
  // server considers live would strand a customer who did nothing wrong, and
  // the server rejects a genuinely expired one at redemption anyway.
  return Number.isFinite(at) && at <= now;
}
