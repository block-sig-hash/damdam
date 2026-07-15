import { NativeModules, Platform } from 'react-native';
import { markEsimActivated } from '../api/esimClient';

export type ActivationPath = 'single_tap' | 'manual';

export async function runSingleFlight<T>(
  state: { current: boolean },
  action: () => Promise<T>,
): Promise<T | undefined> {
  if (state.current) return undefined;
  state.current = true;
  try {
    return await action();
  } finally {
    state.current = false;
  }
}

interface NativeActivationCapability {
  canSwitch: boolean;
  reason: string;
}

interface EsimActivationNativeModule {
  getActivationCapability(iccid: string): Promise<NativeActivationCapability>;
  activateProfile(iccid: string): Promise<void>;
  isNetworkValidated(): Promise<boolean>;
}

function nativeModule(): EsimActivationNativeModule | undefined {
  return NativeModules.EsimActivationModule as EsimActivationNativeModule | undefined;
}

export async function getActivationPath(iccid: string): Promise<ActivationPath> {
  if (Platform.OS !== 'android') return 'manual';
  const native = nativeModule();
  if (!native) return 'manual';
  try {
    const capability = await native.getActivationCapability(iccid);
    return capability.canSwitch ? 'single_tap' : 'manual';
  } catch {
    return 'manual';
  }
}

export async function activateAndroidProfile(iccid: string): Promise<void> {
  const native = nativeModule();
  if (Platform.OS !== 'android' || !native) {
    throw new Error('Use the manual activation guide on this device.');
  }
  await native.activateProfile(iccid);
}

export async function hasValidatedConnectivity(): Promise<boolean> {
  const native = nativeModule();
  if (!native) return false;
  try {
    return await native.isNetworkValidated();
  } catch {
    return false;
  }
}

interface ConfirmActivationOptions {
  attempts?: number;
  intervalMs?: number;
  checkConnectivity?: () => Promise<boolean>;
  wait?: (milliseconds: number) => Promise<void>;
}

export async function confirmActivatedAfterConnectivity(
  accessToken: string,
  packageId: string,
  options: ConfirmActivationOptions = {},
): Promise<'activated' | 'not_connected'> {
  const attempts = options.attempts ?? 6;
  const intervalMs = options.intervalMs ?? 2_000;
  const check = options.checkConnectivity ?? hasValidatedConnectivity;
  const wait = options.wait ?? (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)));
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (await check()) {
      await markEsimActivated(accessToken, packageId);
      return 'activated';
    }
    if (attempt < attempts - 1) await wait(intervalMs);
  }
  return 'not_connected';
}

export async function activateAndConfirmAndroidProfile(
  accessToken: string,
  packageId: string,
  iccid: string,
  options: ConfirmActivationOptions = {},
): Promise<'activated' | 'not_connected'> {
  await activateAndroidProfile(iccid);
  return confirmActivatedAfterConnectivity(accessToken, packageId, options);
}
