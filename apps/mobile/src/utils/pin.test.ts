import { isStrongPin } from './pin';

describe('isStrongPin', () => {
  it('accepts a 4-digit PIN that is neither repeated nor sequential (AC-02.1)', () => {
    expect(isStrongPin('4682')).toBe(true);
    expect(isStrongPin('0392')).toBe(true);
  });

  it('rejects a repeated-digit PIN', () => {
    expect(isStrongPin('1111')).toBe(false);
    expect(isStrongPin('0000')).toBe(false);
  });

  it('rejects an ascending sequential PIN', () => {
    expect(isStrongPin('1234')).toBe(false);
    expect(isStrongPin('4567')).toBe(false);
  });

  it('rejects a descending sequential PIN', () => {
    expect(isStrongPin('4321')).toBe(false);
    expect(isStrongPin('9876')).toBe(false);
  });

  it('rejects anything that is not exactly 4 digits', () => {
    expect(isStrongPin('123')).toBe(false);
    expect(isStrongPin('12345')).toBe(false);
    expect(isStrongPin('12a4')).toBe(false);
    expect(isStrongPin('')).toBe(false);
  });
});
