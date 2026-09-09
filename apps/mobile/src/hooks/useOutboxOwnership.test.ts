import {renderHook} from '@testing-library/react-native';

import {ownershipHolds} from '../services/outboxOwnership';
import {useOutboxOwnership} from './useOutboxOwnership';

const ALICE = 'aaaaaaaa-0000-4000-8000-00000000000a';
const BOB = 'bbbbbbbb-0000-4000-8000-00000000000b';

it('makes an old service observe an account switch and unmount', async () => {
  const {result, rerender, unmount} = await renderHook(
    ({userId}: {userId: string | undefined}) => useOutboxOwnership(userId),
    {initialProps: {userId: ALICE as string | undefined}},
  );
  const aliceServiceOwnership = result.current;
  expect(ownershipHolds(aliceServiceOwnership)).toBe(true);

  await rerender({userId: BOB});
  expect(aliceServiceOwnership.currentOwnerUserId()).toBe(BOB);
  expect(ownershipHolds(aliceServiceOwnership)).toBe(false);
  expect(ownershipHolds(result.current)).toBe(true);

  await unmount();
  expect(result.current.currentOwnerUserId()).toBeUndefined();
});
