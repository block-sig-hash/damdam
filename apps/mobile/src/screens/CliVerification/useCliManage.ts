import { useCallback, useEffect, useState } from 'react';
import {
  getCliStatus,
  reportCliLostSim,
  revokeCli,
  type VerifiedCallerIdentity,
} from '../../api/cliClient';
import { cliErrorMessage } from './cliErrorMessage';

export type CliManageAction = 'revoke' | 'lost_sim';

interface UseCliManageArgs {
  accessToken: string;
}

export interface UseCliManageResult {
  /** undefined while the first load is in flight, null when there's no row yet. */
  identity: VerifiedCallerIdentity | null | undefined;
  errorMessage: string | null;
  actionInFlight: CliManageAction | null;
  refresh: () => Promise<void>;
  revoke: () => Promise<void>;
  reportLostSim: () => Promise<void>;
}

export function useCliManage({ accessToken }: UseCliManageArgs): UseCliManageResult {
  const [identity, setIdentity] = useState<VerifiedCallerIdentity | null | undefined>(
    undefined,
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<CliManageAction | null>(null);

  const refresh = useCallback(async () => {
    try {
      setIdentity(await getCliStatus(accessToken));
    } catch (err) {
      setErrorMessage(cliErrorMessage(err));
    }
  }, [accessToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const runAction = useCallback(
    async (action: CliManageAction, run: () => Promise<void>) => {
      setActionInFlight(action);
      setErrorMessage(null);
      try {
        await run();
        await refresh();
      } catch (err) {
        setErrorMessage(cliErrorMessage(err));
      } finally {
        setActionInFlight(null);
      }
    },
    [refresh],
  );

  const revoke = useCallback(
    () => runAction('revoke', () => revokeCli(accessToken)),
    [runAction, accessToken],
  );
  const reportLostSim = useCallback(
    () => runAction('lost_sim', () => reportCliLostSim(accessToken)),
    [runAction, accessToken],
  );

  return { identity, errorMessage, actionInFlight, refresh, revoke, reportLostSim };
}
