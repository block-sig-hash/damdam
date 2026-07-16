import NetInfo from '@react-native-community/netinfo';
import BackgroundFetch from 'react-native-background-fetch';
import type {CheckInSyncService} from './checkInOutbox';

const TASK_ID = 'com.damdam.checkin.sync';

export async function configureCheckInBackgroundSync(
  service: CheckInSyncService,
): Promise<() => void> {
  await BackgroundFetch.configure(
    {
      minimumFetchInterval: 15,
      stopOnTerminate: false,
      startOnBoot: true,
      enableHeadless: true,
      requiredNetworkType: BackgroundFetch.NETWORK_TYPE_ANY,
    },
    async taskId => {
      try {
        await service.sync(await NetInfo.fetch());
      } finally {
        BackgroundFetch.finish(taskId);
      }
    },
    taskId => BackgroundFetch.finish(taskId),
  );
  await BackgroundFetch.scheduleTask({
    taskId: TASK_ID,
    delay: 30_000,
    periodic: true,
    stopOnTerminate: false,
    startOnBoot: true,
    enableHeadless: true,
    forceAlarmManager: true,
    requiresNetworkConnectivity: true,
    requiredNetworkType: BackgroundFetch.NETWORK_TYPE_ANY,
  });
  return () => {
    BackgroundFetch.stop(TASK_ID).catch(() => undefined);
  };
}
