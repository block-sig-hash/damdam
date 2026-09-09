import { Linking, NativeModules, Platform } from 'react-native';
import { registerDeviceToken } from '../api/pushClient';
import {
  parseActivationDeepLink,
  registerPushInstallation,
  shouldShowDateActivationBanner,
  subscribeToActivationDeepLinks,
} from './activationLinks';

jest.mock('../api/pushClient', () => ({ registerDeviceToken: jest.fn() }));

const originalOs = Platform.OS;
const originalVersion = Platform.Version;

afterEach(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: originalOs });
  Object.defineProperty(Platform, 'Version', { configurable: true, value: originalVersion });
  delete NativeModules.ArrivalPromptModule;
  jest.clearAllMocks();
  jest.restoreAllMocks();
});

it('AC-13.7: starts exactly seven days before departure and does not depend on location permission', () => {
  expect(shouldShowDateActivationBanner('2026-08-10', 'downloaded', new Date('2026-08-02T23:59:59Z'))).toBe(false);
  expect(shouldShowDateActivationBanner('2026-08-10', 'downloaded', new Date('2026-08-03T00:00:00Z'))).toBe(true);
  expect(shouldShowDateActivationBanner('2026-08-10', 'activated', new Date('2026-08-03T00:00:00Z'))).toBe(false);
});

it('AC-13.3: parses the package deep link', () => {
  expect(parseActivationDeepLink('damdam://esim/activate?packageId=package-42')).toBe('package-42');
  expect(parseActivationDeepLink('damdam://other/path?packageId=package-42')).toBeNull();
});

it('AC-13.3: forwards initial and foreground activation links', async () => {
  let handler: ((event: { url: string }) => void) | undefined;
  const remove = jest.fn();
  jest.spyOn(Linking, 'addEventListener').mockImplementation((_type, callback) => {
    handler = callback;
    return { remove } as unknown as ReturnType<typeof Linking.addEventListener>;
  });
  jest.spyOn(Linking, 'getInitialURL').mockResolvedValue('damdam://esim/activate?packageId=initial');
  const onPackage = jest.fn();
  const unsubscribe = subscribeToActivationDeepLinks(onPackage);
  await Promise.resolve();
  handler?.({ url: 'damdam://esim/activate?packageId=foreground' });
  expect(onPackage).toHaveBeenCalledWith('initial');
  expect(onPackage).toHaveBeenCalledWith('foreground');
  unsubscribe();
  expect(remove).toHaveBeenCalled();
});

it('AC-13.1: registers the native FCM token for order and eSIM notifications', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  NativeModules.ArrivalPromptModule = {
    getFcmToken: jest.fn().mockResolvedValue('fcm-token'),
  };

  await expect(registerPushInstallation('access-token')).resolves.toBe('registered');
  expect(registerDeviceToken).toHaveBeenCalledWith('access-token', 'fcm-token', 'android');
});

it('US-30: push registration no longer requests any location permission', async () => {
  // The geofence opt-in was the only caller of the location permissions the
  // retirement removes. Registration must not have inherited that dependency.
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  NativeModules.ArrivalPromptModule = {
    getFcmToken: jest.fn().mockResolvedValue('fcm-token'),
  };
  const request = jest.spyOn(
    require('react-native').PermissionsAndroid,
    'request',
  );

  await registerPushInstallation('access-token');

  expect(request).not.toHaveBeenCalled();
});

it('reports unavailable rather than throwing when the native module is absent', async () => {
  await expect(registerPushInstallation('access-token')).resolves.toBe('unavailable');
  expect(registerDeviceToken).not.toHaveBeenCalled();
});
