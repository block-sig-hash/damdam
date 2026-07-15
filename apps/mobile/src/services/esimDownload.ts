import { NativeModules, Platform } from 'react-native';

interface EsimDownloadModule {
  downloadProfile(activationCodeLpa: string): Promise<void>;
}

export type EsimDownloadResult = 'invoked' | 'manual';

/** Android uses EuiccManager; iOS deliberately follows the QR/manual path. */
export async function downloadEsimProfile(
  activationCodeLpa: string,
): Promise<EsimDownloadResult> {
  if (Platform.OS !== 'android') {
    return 'manual';
  }
  const module = NativeModules.EsimDownloadModule as EsimDownloadModule | undefined;
  if (!module) {
    throw new Error('Direct eSIM download is unavailable on this build.');
  }
  await module.downloadProfile(activationCodeLpa);
  return 'invoked';
}
