import AsyncStorage from '@react-native-async-storage/async-storage';
import { hasSeenEsimWarning, markEsimWarningSeen } from './esimWarningSeen';

describe('esimWarningSeen', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  it('AC-10.6: reports not seen before anything is marked', async () => {
    expect(await hasSeenEsimWarning()).toBe(false);
  });

  it('AC-10.6: reports seen after marking', async () => {
    await markEsimWarningSeen();

    expect(await hasSeenEsimWarning()).toBe(true);
  });

  it('defaults to not-seen if storage read fails (recoverable, not blocking)', async () => {
    jest.spyOn(AsyncStorage, 'getItem').mockRejectedValueOnce(new Error('storage unavailable'));

    expect(await hasSeenEsimWarning()).toBe(false);
  });

  it('does not throw if storage write fails (best-effort)', async () => {
    jest.spyOn(AsyncStorage, 'setItem').mockRejectedValueOnce(new Error('storage unavailable'));

    await expect(markEsimWarningSeen()).resolves.toBeUndefined();
  });
});
