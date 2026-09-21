import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  clearAccount,
  clearAllAccounts,
  readSlice,
  writeSlice,
} from './accountCache';

/**
 * Account-scoped caching (US-38, chunk 21).
 *
 * The test that matters is `does not survive an account switch`. Everything the
 * API proves about isolation is undone if one customer's receipts are still on
 * the handset when the next person signs in, and a shared handset is the normal
 * case for this product rather than an edge one.
 */

describe('accountCache', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  it('keeps what was written, with the time the server observed it', async () => {
    await writeSlice('user-a', 'receipts', [{ reference: 'ORD-1' }], '2026-09-12T10:00:00Z');

    const cached = await readSlice<{ reference: string }[]>('user-a', 'receipts');

    expect(cached?.observedAt).toBe('2026-09-12T10:00:00Z');
    expect(cached?.value).toEqual([{ reference: 'ORD-1' }]);
  });

  it('keeps two accounts apart on one handset', async () => {
    await writeSlice('user-a', 'receipts', ['a'], '2026-09-12T10:00:00Z');
    await writeSlice('user-b', 'receipts', ['b'], '2026-09-12T10:00:00Z');

    expect((await readSlice<string[]>('user-a', 'receipts'))?.value).toEqual(['a']);
    expect((await readSlice<string[]>('user-b', 'receipts'))?.value).toEqual(['b']);
  });

  it('clears every slice for one account and leaves the other alone', async () => {
    await writeSlice('user-a', 'receipts', ['a'], '2026-09-12T10:00:00Z');
    await writeSlice('user-a', 'usage', { bytes: 1 }, '2026-09-12T10:00:00Z');
    await writeSlice('user-a', 'installation', { steps: 3 }, '2026-09-12T10:00:00Z');
    await writeSlice('user-b', 'receipts', ['b'], '2026-09-12T10:00:00Z');

    const cleared = await clearAccount('user-a');

    expect(cleared).toBe(3);
    expect(await readSlice('user-a', 'receipts')).toBeNull();
    expect(await readSlice('user-a', 'usage')).toBeNull();
    expect(await readSlice('user-a', 'installation')).toBeNull();
    expect((await readSlice<string[]>('user-b', 'receipts'))?.value).toEqual(['b']);
  });

  it('does not leave one account reading another account cache after a switch', async () => {
    await writeSlice('user-a', 'receipts', ['private to a'], '2026-09-12T10:00:00Z');

    await clearAccount('user-a');

    expect(await readSlice('user-b', 'receipts')).toBeNull();
    expect(await readSlice('user-a', 'receipts')).toBeNull();
  });

  it('clears every account when the whole device is handed on', async () => {
    await writeSlice('user-a', 'receipts', ['a'], '2026-09-12T10:00:00Z');
    await writeSlice('user-b', 'receipts', ['b'], '2026-09-12T10:00:00Z');

    const cleared = await clearAllAccounts();

    expect(cleared).toBe(2);
    expect(await readSlice('user-a', 'receipts')).toBeNull();
    expect(await readSlice('user-b', 'receipts')).toBeNull();
  });

  it('leaves other apps keys alone', async () => {
    await AsyncStorage.setItem('damdam.pendingOrder.v1', 'something else');
    await writeSlice('user-a', 'receipts', ['a'], '2026-09-12T10:00:00Z');

    await clearAllAccounts();

    expect(await AsyncStorage.getItem('damdam.pendingOrder.v1')).toBe('something else');
  });

  it('treats an unreadable cache as nothing saved rather than an error', async () => {
    await AsyncStorage.setItem('damdam.account.v1.user-a.receipts', 'not json');

    await expect(readSlice('user-a', 'receipts')).resolves.toBeNull();
  });

  it('treats a payload with no observation time as nothing saved', async () => {
    // A balance with no age is the thing the product must never render.
    await AsyncStorage.setItem(
      'damdam.account.v1.user-a.usage',
      JSON.stringify({ value: { bytes: 1 } }),
    );

    await expect(readSlice('user-a', 'usage')).resolves.toBeNull();
  });

  it('clearing an account that cached nothing is not an error', async () => {
    await expect(clearAccount('never-signed-in')).resolves.toBe(0);
  });
});
