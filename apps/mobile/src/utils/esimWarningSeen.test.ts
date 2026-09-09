import AsyncStorage from '@react-native-async-storage/async-storage';
import { hasSeenEsimWarning, markEsimWarningSeen } from './esimWarningSeen';

const TEST_USER_ID = '11111111-1111-4111-8111-111111111111';

describe('esimWarningSeen', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  it('AC-10.6: reports not seen before anything is marked', async () => {
    expect(await hasSeenEsimWarning(TEST_USER_ID)).toBe(false);
  });

  it('AC-10.6: reports seen after marking', async () => {
    await markEsimWarningSeen(TEST_USER_ID);

    expect(await hasSeenEsimWarning(TEST_USER_ID)).toBe(true);
  });

  it('defaults to not-seen if storage read fails (recoverable, not blocking)', async () => {
    jest.spyOn(AsyncStorage, 'getItem').mockRejectedValueOnce(new Error('storage unavailable'));

    expect(await hasSeenEsimWarning(TEST_USER_ID)).toBe(false);
  });

  it('does not throw if storage write fails (best-effort)', async () => {
    jest.spyOn(AsyncStorage, 'setItem').mockRejectedValueOnce(new Error('storage unavailable'));

    await expect(markEsimWarningSeen(TEST_USER_ID)).resolves.toBeUndefined();
  });
});
