/**
 * AC-02.1: PIN must be 4 digits, not sequential or repeated. Mirrors
 * apps/api/app/auth/schemas.py's is_strong_pin exactly, so client-side
 * validation never accepts a PIN the server would reject.
 */
export function isStrongPin(value: string): boolean {
  if (!/^\d{4}$/.test(value)) return false;
  if (new Set(value).size === 1) return false;

  const digits = value.split('').map(Number);
  const differences = digits.slice(1).map((digit, index) => digit - digits[index]);
  const isAscending = differences.every((difference) => difference === 1);
  const isDescending = differences.every((difference) => difference === -1);
  return !isAscending && !isDescending;
}
