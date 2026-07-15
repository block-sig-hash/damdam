import { Linking, NativeModules, PermissionsAndroid, Platform } from 'react-native';
import { registerDeviceToken } from '../api/pushClient';

export const ARRIVAL_NOTIFICATION_COPY =
  "You've arrived in Saudi Arabia. Tap to activate your DamDam data — takes 30 seconds.";
export const ARRIVAL_DEEP_LINK_PREFIX = 'damdam://esim/activate';

interface ArrivalPromptNativeModule {
  getFcmToken(): Promise<string>;
  registerJeddahGeofence(packageId: string): Promise<void>;
}

function nativeModule(): ArrivalPromptNativeModule | undefined {
  return NativeModules.ArrivalPromptModule as ArrivalPromptNativeModule | undefined;
}

export function shouldShowDateActivationBanner(
  departureDate: string | null,
  esimStatus: string,
  now: Date = new Date(),
): boolean {
  if (!departureDate || esimStatus === 'activated') return false;
  const departure = new Date(`${departureDate}T00:00:00.000Z`);
  if (Number.isNaN(departure.getTime())) return false;
  const startsAt = departure.getTime() - 7 * 24 * 60 * 60 * 1000;
  return now.getTime() >= startsAt;
}

export function parseActivationDeepLink(url: string): string | null {
  if (!url.startsWith(ARRIVAL_DEEP_LINK_PREFIX)) return null;
  const query = url.split('?')[1];
  if (!query) return null;
  return new URLSearchParams(query).get('packageId');
}

export function subscribeToActivationDeepLinks(
  onPackage: (packageId: string) => void,
): () => void {
  const handle = ({ url }: { url: string }) => {
    const packageId = parseActivationDeepLink(url);
    if (packageId) onPackage(packageId);
  };
  const subscription = Linking.addEventListener('url', handle);
  Linking.getInitialURL().then(url => {
    if (url) handle({ url });
  });
  return () => subscription.remove();
}

export async function registerPushInstallation(
  accessToken: string,
): Promise<'registered' | 'unavailable'> {
  const native = nativeModule();
  if (!native) return 'unavailable';
  try {
    const token = await native.getFcmToken();
    await registerDeviceToken(
      accessToken,
      token,
      Platform.OS === 'ios' ? 'ios' : 'android',
    );
    return 'registered';
  } catch {
    return 'unavailable';
  }
}

export async function optIntoArrivalGeofence(
  packageId: string,
): Promise<'registered' | 'denied' | 'unsupported'> {
  const native = nativeModule();
  if (!native) return 'unsupported';
  if (Platform.OS === 'android') {
    const fine = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
    );
    if (fine !== PermissionsAndroid.RESULTS.GRANTED) return 'denied';
    if (Platform.Version >= 29) {
      const background = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.ACCESS_BACKGROUND_LOCATION,
      );
      if (background !== PermissionsAndroid.RESULTS.GRANTED) return 'denied';
    }
    if (Platform.Version >= 33) {
      const notifications = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
      );
      if (notifications !== PermissionsAndroid.RESULTS.GRANTED) return 'denied';
    }
  }
  try {
    await native.registerJeddahGeofence(packageId);
    return 'registered';
  } catch {
    return 'unsupported';
  }
}
