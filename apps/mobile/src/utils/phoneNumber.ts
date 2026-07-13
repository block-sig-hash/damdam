/**
 * Nigerian mobile number format (AC-01.1/AC-01.2, prd.md §4.1).
 * Mirrors the backend pattern exactly (apps/api/app/auth/schemas.py
 * NIGERIAN_PHONE_PATTERN) so client-side validation never accepts a
 * number the server would reject.
 */
const NIGERIAN_PHONE_PATTERN = /^0(?:70|80|81|90|91)\d{8}$/;

export function isValidNigerianPhoneNumber(value: string): boolean {
  return NIGERIAN_PHONE_PATTERN.test(value);
}

export function toE164(value: string): string {
  return `+234${value.slice(1)}`;
}

/** Strips everything but digits, for normalizing raw text-input value. */
export function digitsOnly(value: string): string {
  return value.replace(/\D/g, '');
}

export function formatNigerianPhoneForDisplay(value: string): string {
  const digits = digitsOnly(value).slice(0, 11);
  const parts = [digits.slice(0, 4), digits.slice(4, 7), digits.slice(7, 11)].filter(Boolean);
  return parts.join(' ');
}
