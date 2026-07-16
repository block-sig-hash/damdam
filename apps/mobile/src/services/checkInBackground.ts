import NetInfo from '@react-native-community/netinfo';
import BackgroundFetch from 'react-native-background-fetch';
import type {CheckInSyncService} from './checkInOutbox';
import type {SOSSyncService} from './sosOutbox';

const TASK_ID = 'com.damdam.checkin.sync';
const SOS_TASK_ID = 'com.damdam.sos.sync';

export async function configureCheckInBackgroundSync(
  service: CheckInSyncService,
  sosService?: SOSSyncService,
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
        if (sosService) await sosService.sync(await NetInfo.fetch());
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
  if (sosService) {
    await BackgroundFetch.scheduleTask({
      taskId: SOS_TASK_ID,
      delay: 10_000,
      periodic: true,
      stopOnTerminate: false,
      startOnBoot: true,
      enableHeadless: true,
      forceAlarmManager: true,
      requiresNetworkConnectivity: true,
      requiredNetworkType: BackgroundFetch.NETWORK_TYPE_ANY,
    });
  }
  return () => {
    BackgroundFetch.stop(TASK_ID).catch(() => undefined);
    if (sosService) BackgroundFetch.stop(SOS_TASK_ID).catch(() => undefined);
  };
}
