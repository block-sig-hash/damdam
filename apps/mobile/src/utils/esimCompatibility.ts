import { NativeModules, Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';

export interface EsimCompatibilityResult {
  platform: 'ios' | 'android';
  deviceModel: string;
  osVersion: string | null;
  supported: boolean;
}

/**
 * iPhone XS was the first eSIM-capable generation and reports a
 * hardware identifier of the form "iPhoneN,M" via getDeviceId() —
 * XS/XS Max/XR are all "iPhone11,x". There's no capability API on
 * iOS (prd.md §5.4), so "iPhone XS and later" is checked as
 * generation >= 11 rather than a hand-maintained model list, which
 * would need a yearly update and is a real source of transcription
 * error to get right from a fixed list. Anything that doesn't match
 * the iPhoneN,M pattern (simulators, unrecognized future formats)
 * is treated as unsupported — the conservative default, since a
 * false "unsupported" just shows the warning modal (recoverable via
 * Continue/QR), while a false "supported" would be a dead end.
 */
const IOS_ESIM_CAPABLE_GENERATION_FLOOR = 11;

function isSupportediOSDeviceId(deviceId: string): boolean {
  const match = /^iPhone(\d+),\d+$/.exec(deviceId);
  if (!match) {
    return false;
  }
  return Number(match[1]) >= IOS_ESIM_CAPABLE_GENERATION_FLOOR;
}

async function checkAndroidEuicc(): Promise<boolean> {
  try {
    const module = NativeModules.EsimCompatibility as
      | { hasEuicc(): Promise<boolean> }
      | undefined;
    return (await module?.hasEuicc()) ?? false;
  } catch {
    return false;
  }
}

/** AC-10.1: platform-specific device eSIM capability check. */
export async function checkEsimCompatibility(): Promise<EsimCompatibilityResult> {
  const deviceModel = DeviceInfo.getModel();
  const osVersion = DeviceInfo.getSystemVersion();

  if (Platform.OS === 'android') {
    return {
      platform: 'android',
      deviceModel,
      osVersion,
      supported: await checkAndroidEuicc(),
    };
  }

  return {
    platform: 'ios',
    deviceModel,
    osVersion,
    supported: isSupportediOSDeviceId(DeviceInfo.getDeviceId()),
  };
}
