/**
 * Canned data for the screenshot harness (screenshotHarness/README.md).
 * None of this is real user data -- it exists only to give network- or
 * storage-dependent screens something to render without a live API.
 */
import type { PricingTier } from '../src/api/pricingClient';
import type { EsimProfile } from '../src/api/esimClient';
import type { ActivationRedemption } from '../src/api/activationClient';
import type { CallHistoryItem } from '../src/api/voiceClient';
import type { VoiceCallSession, VoiceCallState } from '../src/services/voiceGateway';

// 1x1 transparent PNG -- stands in for a real QR code image URL so
// <Image> has something to decode without a network round-trip.
export const PLACEHOLDER_IMAGE_DATA_URI =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

export const FIXTURE_PHONE_NUMBER = '+2348012345678';
export const FIXTURE_ACCESS_TOKEN = 'harness-fixture-access-token';
export const FIXTURE_PACKAGE_ID = 'harness-fixture-package-id';

export const FIXTURE_PRICING_TIERS: PricingTier[] = [
  { id: 'tier-starter', name: 'Starter', ngn_price: 15000, data_gb: 5, pstn_minutes: 30, is_group_tier: false },
  { id: 'tier-basic', name: 'Basic', ngn_price: 25000, data_gb: 10, pstn_minutes: 60, is_group_tier: false },
  { id: 'tier-standard', name: 'Standard', ngn_price: 40000, data_gb: 20, pstn_minutes: 120, is_group_tier: false },
  {
    id: 'tier-family',
    name: 'Family',
    ngn_price: 18000,
    data_gb: 10,
    pstn_minutes: 60,
    is_group_tier: true,
    min_group_size: 2,
    max_group_size: 8,
  },
];

export const FIXTURE_ESIM_PROFILE: EsimProfile = {
  esim_profile_id: 'harness-esim-profile',
  iccid: '8923410123456789012',
  activation_code_lpa: 'LPA:1$rsp.example.com$HARNESS-ACTIVATION-CODE',
  qr_code_url: PLACEHOLDER_IMAGE_DATA_URI,
  status: 'issued',
  downloaded_at: null,
  activated_at: null,
};

export const FIXTURE_ACTIVATION_REDEMPTION: ActivationRedemption = {
  package_id: FIXTURE_PACKAGE_ID,
  pricing_tier_name: 'Standard',
  data_gb_total: 20,
  pstn_minutes_total: 120,
  status: 'active',
};

export const FIXTURE_CALL_HISTORY: CallHistoryItem[] = [
  {
    id: 'call-1',
    call_type: 'app_to_app',
    to_number: '+2348022223333',
    duration_seconds: 184,
    pstn_minutes_charged: 0,
    started_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  },
  {
    id: 'call-2',
    call_type: 'pstn',
    to_number: '+2348099998888',
    duration_seconds: 95,
    pstn_minutes_charged: 1.6,
    started_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
  },
];

/** A VoiceCallSession that renders ActiveCallScreen in a static "connected" state. */
export function createFixtureCallSession(): VoiceCallSession {
  return {
    callType: 'app_to_app',
    displayNumber: '+234 802 222 3333',
    subscribeState(listener: (state: VoiceCallState) => void) {
      listener('connected');
      return () => undefined;
    },
    subscribeDuration(listener: (seconds: number) => void) {
      listener(47);
      return () => undefined;
    },
    toggleMute: () => Promise.resolve(false),
    toggleSpeaker: () => Promise.resolve(false),
    hangup: () => Promise.resolve(),
  };
}
