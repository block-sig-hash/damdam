/**
 * Nigerian mobile number validation for CLI verification (AC-14.10).
 * Deliberately broader than utils/phoneNumber.ts's login-number pattern:
 * mirrors apps/api/app/voice/nigerian_numbers.py exactly, since AC-14.10
 * lets a pilgrim verify any Nigerian mobile number, not just the narrower
 * set of prefixes the account login OTP flow accepts.
 */
const LOCAL_FORMAT = /^0\d{10}$/;
const PLUS_COUNTRY_CODE_FORMAT = /^\+234\d{10}$/;
const RESERVED_NON_SUBSCRIBER_PREFIXES = ['700', '900'];

export function isValidCliPhoneNumber(value: string): boolean {
  const compact = value.replace(/[\s()-]/g, '');
  let national: string | null = null;
  if (LOCAL_FORMAT.test(compact)) {
    national = compact.slice(1);
  } else if (PLUS_COUNTRY_CODE_FORMAT.test(compact)) {
    national = compact.slice(4);
  }
  if (!national) return false;
  if (!['7', '8', '9'].includes(national[0])) return false;
  if (RESERVED_NON_SUBSCRIBER_PREFIXES.includes(national.slice(0, 3))) return false;
  return true;
}

/** Strips everything but digits, for normalizing raw text-input value. */
export function cliDigitsOnly(value: string): string {
  return value.replace(/\D/g, '');
}
