/**
 * eSIM activation deep links, push installation and the date-based activation
 * banner.
 *
 * These were previously in `arrivalPrompts.ts` alongside Saudi arrival
 * geofencing. The geofencing is retired with the Hajj framing (US-30), but
 * none of what remains here depends on it: the deep link opens the activation
 * flow, the push registration serves order and eSIM notifications, and the
 * banner is deliberately permission-free -- it keys on the departure date, not
 * on the device's location.
 */

import { Linking, NativeModules, Platform } from 'react-native';
import { registerDeviceToken } from '../api/pushClient';

export const ACTIVATION_DEEP_LINK_PREFIX = 'damdam://esim/activate';

interface PushInstallationNativeModule {
  getFcmToken(): Promise<string>;
}

function nativeModule(): PushInstallationNativeModule | undefined {
  return NativeModules.ArrivalPromptModule as
    | PushInstallationNativeModule
    | undefined;
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
  if (!url.startsWith(ACTIVATION_DEEP_LINK_PREFIX)) return null;
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
