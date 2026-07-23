import { useCallback, useEffect, useRef, useState } from 'react';
import {
  EsimApiError,
  EsimProfile,
  getEsim,
  issueEsim,
  markEsimDownloaded,
} from '../../api/esimClient';
import { downloadEsimProfile } from '../../services/esimDownload';
import {i18n} from '../../i18n';

const RETRY_POLL_MS = 10_000;

export type EsimProfilePhase = 'loading' | 'ready' | 'queued' | 'downloading' | 'downloaded';

export function useEsimProfile(accessToken: string, packageId: string) {
  const [phase, setPhase] = useState<EsimProfilePhase>('loading');
  const [profile, setProfile] = useState<EsimProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setError(null);
    try {
      // /issue is idempotent and, unlike GET, returns the Android LPA string.
      const issued = await issueEsim(accessToken, packageId);
      setProfile(issued);
      setPhase(issued.status === 'downloaded' ? 'downloaded' : 'ready');
    } catch (caught) {
      setPhase('queued');
      setError(
        caught instanceof EsimApiError && caught.code === 'aggregator_unavailable'
          ? i18n.t('errors.queued', {ns: 'esim'})
          : caught instanceof Error
            ? caught.message
            : i18n.t('errors.queuedFallback', {ns: 'esim'}),
      );
    } finally {
      inFlight.current = false;
    }
  }, [accessToken, packageId]);

  const pollForIssuedProfile = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      await getEsim(accessToken, packageId);
      // GET intentionally omits the LPA activation string. Once a profile exists,
      // the idempotent issue endpoint returns that existing profile without making
      // another vendor request, so the Android download action can be hydrated.
      const issued = await issueEsim(accessToken, packageId);
      setProfile(issued);
      setError(null);
      setPhase(issued.status === 'downloaded' ? 'downloaded' : 'ready');
    } catch {
      // The durable server-side job owns the 60-second/5-minute retry schedule.
      // A missing profile simply remains queued until the next read-only poll.
    } finally {
      inFlight.current = false;
    }
  }, [accessToken, packageId]);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  useEffect(() => {
    if (phase !== 'queued') return;
    const timer = setInterval(
      () => pollForIssuedProfile().catch(() => undefined),
      RETRY_POLL_MS,
    );
    return () => clearInterval(timer);
  }, [phase, pollForIssuedProfile]);

  const download = useCallback(async () => {
    if (inFlight.current || !profile?.activation_code_lpa) return;
    inFlight.current = true;
    setPhase('downloading');
    setError(null);
    try {
      const result = await downloadEsimProfile(profile.activation_code_lpa);
      if (result === 'manual') {
        setPhase('ready');
        return;
      }
      const updated = await markEsimDownloaded(accessToken, packageId);
      setProfile(current => ({ ...current!, status: updated.status }));
      setPhase('downloaded');
    } catch (caught) {
      setPhase('ready');
      setError(caught instanceof Error ? caught.message : i18n.t('errors.downloadFailed', {ns: 'esim'}));
    } finally {
      inFlight.current = false;
    }
  }, [accessToken, packageId, profile]);

  const confirmManualDownload = useCallback(async () => {
    if (inFlight.current || !profile) return;
    inFlight.current = true;
    setPhase('downloading');
    try {
      const updated = await markEsimDownloaded(accessToken, packageId);
      setProfile(current => ({ ...current!, status: updated.status }));
      setPhase('downloaded');
    } catch (caught) {
      setPhase('ready');
      setError(caught instanceof Error ? caught.message : i18n.t('errors.statusFailed', {ns: 'esim'}));
    } finally {
      inFlight.current = false;
    }
  }, [accessToken, packageId, profile]);

  return { phase, profile, error, retry: load, download, confirmManualDownload };
}
