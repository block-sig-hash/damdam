import { digitsOnly, formatNigerianPhoneForDisplay, isValidNigerianPhoneNumber, toE164 } from './phoneNumber';

describe('isValidNigerianPhoneNumber', () => {
  it.each(['07012345678', '08012345678', '08112345678', '09012345678', '09112345678'])(
    'accepts %s',
    (value) => {
      expect(isValidNigerianPhoneNumber(value)).toBe(true);
    },
  );

  it.each([
    '+2348012345678',
    '2348012345678',
    '0801234567',
    '080123456789',
    '07112345678',
    '0801234567a',
    '',
  ])('rejects %s', (value) => {
    expect(isValidNigerianPhoneNumber(value)).toBe(false);
  });
});

describe('toE164', () => {
  it('replaces the leading 0 with +234', () => {
    expect(toE164('08012345678')).toBe('+2348012345678');
  });
});

describe('digitsOnly', () => {
  it('strips non-digit characters', () => {
    expect(digitsOnly('080 1234 5678')).toBe('08012345678');
  });
});

describe('formatNigerianPhoneForDisplay', () => {
  it('groups digits for readability', () => {
    expect(formatNigerianPhoneForDisplay('08012345678')).toBe('0801 234 5678');
  });

  it('handles partial input without throwing', () => {
    expect(formatNigerianPhoneForDisplay('080')).toBe('080');
  });
});
