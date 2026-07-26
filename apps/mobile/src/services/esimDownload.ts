import { NativeModules, Platform } from 'react-native';
import {i18n} from '../i18n';

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
    throw new Error(i18n.t('errors.directUnavailable', {ns: 'esim'}));
  }
  await module.downloadProfile(activationCodeLpa);
  return 'invoked';
}
