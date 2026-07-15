import { Linking, NativeModules, PermissionsAndroid, Platform } from 'react-native';
import { registerDeviceToken } from '../api/pushClient';
import {
  ARRIVAL_NOTIFICATION_COPY,
  optIntoArrivalGeofence,
  parseActivationDeepLink,
  registerPushInstallation,
  shouldShowDateActivationBanner,
  subscribeToActivationDeepLinks,
} from './arrivalPrompts';

jest.mock('../api/pushClient', () => ({ registerDeviceToken: jest.fn() }));

const originalOs = Platform.OS;
const originalVersion = Platform.Version;

afterEach(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: originalOs });
  Object.defineProperty(Platform, 'Version', { configurable: true, value: originalVersion });
  delete NativeModules.ArrivalPromptModule;
  jest.restoreAllMocks();
});

it('AC-13.7: starts exactly seven days before departure and does not depend on location permission', () => {
  expect(shouldShowDateActivationBanner('2026-08-10', 'downloaded', new Date('2026-08-02T23:59:59Z'))).toBe(false);
  expect(shouldShowDateActivationBanner('2026-08-10', 'downloaded', new Date('2026-08-03T00:00:00Z'))).toBe(true);
  expect(shouldShowDateActivationBanner('2026-08-10', 'activated', new Date('2026-08-03T00:00:00Z'))).toBe(false);
});

it('AC-13.2/13.3: preserves exact copy and parses the package deep link', () => {
  expect(ARRIVAL_NOTIFICATION_COPY).toBe("You've arrived in Saudi Arabia. Tap to activate your DamDam data — takes 30 seconds.");
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

it('AC-13.1: registers the native FCM token and opt-in geofence after permissions', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  Object.defineProperty(Platform, 'Version', { configurable: true, value: 35 });
  NativeModules.ArrivalPromptModule = {
    getFcmToken: jest.fn().mockResolvedValue('fcm-token-long-enough-for-validation'),
    registerJeddahGeofence: jest.fn().mockResolvedValue(undefined),
  };
  jest.spyOn(PermissionsAndroid, 'request').mockResolvedValue(PermissionsAndroid.RESULTS.GRANTED);
  (registerDeviceToken as jest.Mock).mockResolvedValue({ registered: true });

  await expect(registerPushInstallation('access')).resolves.toBe('registered');
  await expect(optIntoArrivalGeofence('package-1')).resolves.toBe('registered');
  expect(registerDeviceToken).toHaveBeenCalledWith(
    'access',
    'fcm-token-long-enough-for-validation',
    'android',
  );
  expect(NativeModules.ArrivalPromptModule.registerJeddahGeofence).toHaveBeenCalledWith('package-1');
});

it('AC-13.7: denied geofence permission stops only the optional geofence registration', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  NativeModules.ArrivalPromptModule = { registerJeddahGeofence: jest.fn() };
  jest.spyOn(PermissionsAndroid, 'request').mockResolvedValue(PermissionsAndroid.RESULTS.DENIED);
  await expect(optIntoArrivalGeofence('package-1')).resolves.toBe('denied');
  expect(shouldShowDateActivationBanner('2026-07-20', 'downloaded', new Date('2026-07-15T00:00:00Z'))).toBe(true);
  expect(NativeModules.ArrivalPromptModule.registerJeddahGeofence).not.toHaveBeenCalled();
});
