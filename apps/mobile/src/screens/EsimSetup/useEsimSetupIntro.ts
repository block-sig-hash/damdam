import { useCallback, useEffect, useState } from 'react';
import { Linking } from 'react-native';
import { DeviceCompatibilityPayload, logDeviceCompatibility } from '../../api/esimClient';
import { SUPPORT_WHATSAPP_NUMBER } from '../../config/env';
import { checkEsimCompatibility } from '../../utils/esimCompatibility';
import { hasSeenEsimWarning, markEsimWarningSeen } from '../../utils/esimWarningSeen';
import {i18n} from '../../i18n';

export type EsimSetupStage = 'checking' | 'compatible' | 'warning' | 'qr-only';

interface UseEsimSetupIntroArgs {
  accessToken: string;
  /** Scopes the one-time warning dismissal to this account (US-29). */
  userId: string;
  packageId: string;
}

export interface UseEsimSetupIntroResult {
  stage: EsimSetupStage;
  /** AC-10.4: proceeds without blocking, whichever button was pressed. */
  handleWarningContinue: () => Promise<void>;
  /** AC-10.5: opens WhatsApp with a pre-filled order reference, then proceeds the same as Continue. */
  handleWarningSupport: () => Promise<void>;
}

/**
 * Screen 15 (eSIM Setup Intro) + Screen 16 (Device Compatibility
 * Warning modal), docs/frontend-mobile.md. The actual QR/download
 * screen this hands off to is US-11's scope, not built here — both
 * the "compatible" and post-warning "qr-only" outcomes hand off via
 * the same onProceed the screen calls, to whatever stands in for it.
 */
export function useEsimSetupIntro({
  accessToken,
  userId,
  packageId,
}: UseEsimSetupIntroArgs): UseEsimSetupIntroResult {
  const [stage, setStage] = useState<EsimSetupStage>('checking');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const result = await checkEsimCompatibility();
      if (cancelled) {
        return;
      }
      const payload: DeviceCompatibilityPayload = {
        platform: result.platform,
        device_model: result.deviceModel,
        os_version: result.osVersion ?? undefined,
        esim_supported: result.supported,
      };
      if (result.supported) {
        // AC-10.2: no modal gates the compatible path, so this logs
        // immediately rather than waiting on a user action.
        logDeviceCompatibility(accessToken, payload).catch(() => {
          // Best-effort — a logging failure shouldn't block a
          // pilgrim who has a perfectly usable, compatible device.
        });
        setStage('compatible');
        return;
      }
      if (await hasSeenEsimWarning(userId)) {
        if (!cancelled) {
          setStage('qr-only');
        }
        return;
      }
      // AC-10.7: logged on detection, not deferred to Continue/Support,
      // so a pilgrim who abandons the app after seeing the warning
      // (backgrounds/force-quits without tapping either button) still
      // gets flagged for HTO follow-up — the population AC-10.7 exists
      // to catch is exactly the one most likely to not act further.
      logDeviceCompatibility(accessToken, payload).catch(() => {});
      if (!cancelled) {
        setStage('warning');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken, userId]);

  const resolveWarning = useCallback(async () => {
    // The compatibility check (and its log/flag) already fired on
    // detection, above — this only records that the warning has been
    // shown, per AC-10.6, so it isn't repeated on a later visit.
    await markEsimWarningSeen(userId);
    setStage('qr-only');
  }, [userId]);

  const handleWarningContinue = useCallback(async () => {
    await resolveWarning();
  }, [resolveWarning]);

  const handleWarningSupport = useCallback(async () => {
    const message = encodeURIComponent(
      i18n.t('compatibility.supportMessage', {ns: 'esim', reference: packageId}),
    );
    Linking.openURL(`https://wa.me/${SUPPORT_WHATSAPP_NUMBER}?text=${message}`).catch(() => {
      // Best-effort — WhatsApp not being installed shouldn't block
      // the pilgrim from still reaching the QR fallback.
    });
    await resolveWarning();
  }, [resolveWarning, packageId]);

  return { stage, handleWarningContinue, handleWarningSupport };
}
