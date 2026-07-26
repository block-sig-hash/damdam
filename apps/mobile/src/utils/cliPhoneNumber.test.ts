import { isValidCliPhoneNumber } from './cliPhoneNumber';

describe('isValidCliPhoneNumber', () => {
  it.each(['08031234567', '+2348031234567', '0803 123 4567'])(
    'accepts a common Nigerian mobile format: %s',
    (value) => {
      expect(isValidCliPhoneNumber(value)).toBe(true);
    },
  );

  it.each([
    ['12345', 'short code'],
    ['080312345', 'too short'],
    ['080312345678', 'too long'],
    ['+15551234567', 'non-Nigerian'],
    ['07001234567', 'reserved 700 prefix'],
    ['09001234567', 'reserved 900 prefix'],
    ['01031234567', 'non-mobile leading digit'],
  ])('rejects %s (%s)', (value) => {
    expect(isValidCliPhoneNumber(value)).toBe(false);
  });
});
