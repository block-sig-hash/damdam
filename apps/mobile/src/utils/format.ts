/**
 * Turning what the API sends into what a person reads.
 *
 * Introduced by chunk 19's purchase journey and moved here by chunk 20, which
 * needs the same helpers for My Line. Two screens formatting the same amount
 * through two copies of this is how the price on a receipt comes to differ from
 * the price on the plan card.
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


const MINUTES_PER_HOUR = 60;
const MINUTES_PER_DAY = 60 * 24;

/**
 * How old a reading is, in the coarsest unit that is still honest.
 *
 * Coarse on purpose. Carrier usage arrives late and irregularly, so "3 hours
 * ago" is the useful fact and "2h 47m ago" implies a precision the pipeline
 * does not have. `null` in means nobody has ever reported, which the caller
 * renders as its own state rather than as an age.
 */
export function observedAgeMinutes(
  observedAt: string | null,
  now: number = Date.now(),
): number | null {
  if (observedAt === null) {
    return null;
  }
  const at = new Date(observedAt).getTime();
  if (!Number.isFinite(at)) {
    return null;
  }
  return Math.max(0, Math.floor((now - at) / 60_000));
}

export type AgeUnit = 'now' | 'minutes' | 'hours' | 'days';

export function ageUnit(minutes: number): { unit: AgeUnit; value: number } {
  if (minutes < 1) {
    return { unit: 'now', value: 0 };
  }
  if (minutes < MINUTES_PER_HOUR) {
    return { unit: 'minutes', value: minutes };
  }
  if (minutes < MINUTES_PER_DAY) {
    return { unit: 'hours', value: Math.floor(minutes / MINUTES_PER_HOUR) };
  }
  return { unit: 'days', value: Math.floor(minutes / MINUTES_PER_DAY) };
}

/**
 * A fraction of an allowance that is left, clamped to 0-1.
 *
 * A zero total returns 0 rather than dividing: a plan with no data allowance is
 * not a plan that is 100% full, and the meter for it should read empty while the
 * label says what the plan actually includes.
 */
export function remainingFraction(remaining: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return Math.min(1, Math.max(0, remaining / total));
}

/** Seconds as whole minutes, for a calls meter. */
export function minutesFromSeconds(seconds: number): number {
  return Math.max(0, Math.round(seconds / 60));
}
