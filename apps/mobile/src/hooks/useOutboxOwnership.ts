import {useEffect, useMemo, useRef} from 'react';

import type {OutboxOwnership} from '../services/outboxOwnership';

/**
 * Bind one service instance to its owner while exposing the account that is
 * current now. Old instances share the ref, so an account switch or unmount is
 * observable by an in-flight send before it consumes a queued row.
 */
export function useOutboxOwnership(userId: string | undefined): OutboxOwnership {
  const currentOwnerUserId = useRef(userId);
  currentOwnerUserId.current = userId;

  useEffect(() => {
    currentOwnerUserId.current = userId;
    return () => {
      // On a prop change React renders the new owner before cleaning up the old
      // effect. Do not let A's cleanup erase B; do clear on a real unmount.
      if (currentOwnerUserId.current === userId) {
        currentOwnerUserId.current = undefined;
      }
    };
  }, [userId]);

  return useMemo(
    () => ({
      ownerUserId: userId ?? '',
      currentOwnerUserId: () => currentOwnerUserId.current,
    }),
    [userId],
  );
}
