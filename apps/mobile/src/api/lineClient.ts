import { apiRequest } from './http';

/**
 * Mirrors apps/api/app/line/schemas.py (US-38, chunk 20).
 *
 * Read the nullability before the fields. `installation` and `line` are **null**
 * for an internet-calling grant — there is no profile and no carrier line, so
 * `not_installed` would be a false negative rather than a fact — and every
 * `*_observed_at` is nullable because "we have never been told" is a distinct
 * answer from "we were told, and it was false".
 */

export type LineDelivery = 'carrier_esim' | 'internet';
export type NumberStatus = 'assigned' | 'pending' | 'not_included';
export type Freshness = 'fresh' | 'stale' | 'unknown';

export interface AssignedNumber {
  e164: string;
  country: string;
  assigned_at: string;
}

export interface InstallationView {
  state: 'not_installed' | 'installed' | 'removed';
  installed_at: string | null;
  /** The supplier released the profile. Emphatically not an installation. */
  profile_released_at: string | null;
  credential_available: boolean;
  credential_unavailable_reason: string | null;
  delivery_count: number;
  one_time_use: boolean;
  /** False for a one-time profile, always. There is no re-download. */
  reinstall_available: boolean;
  reinstall_blocked_reason: string | null;
}

export interface LineStateView {
  carrier: string;
  activation_state: 'pending' | 'activating' | 'active' | 'suspended' | 'terminated';
  network_state: 'unknown' | 'attached' | 'detached';
  network_state_observed_at: string | null;
  provider_status: string | null;
  provider_status_observed_at: string | null;
  voice_enabled: boolean;
  voice_enabled_observed_at: string | null;
}

export interface UsageView {
  data_bytes_total: number;
  data_bytes_used: number;
  data_bytes_remaining: number;
  voice_seconds_total: number;
  voice_seconds_used: number;
  voice_seconds_remaining: number;
  observed_at: string | null;
  freshness: Freshness;
  has_provisional: boolean;
  expires_at: string | null;
  expired: boolean;
}

export interface RestrictionView {
  suspended: boolean;
  enforcement: string;
  control_state: string;
  requested_limit_bytes: number | null;
  confirmed_limit_bytes: number | null;
  detail: string | null;
}

export interface TopUpView {
  applied_data_bytes: number;
  applied_voice_seconds: number;
  applied_extra_days: number;
  pending_count: number;
}

export interface CallDestination {
  country: string;
  origin_country?: string | null;
  destination_kind: string;
  per_minute_amount: string;
  setup_amount: string;
  increment_seconds: number;
  minimum_seconds: number;
}

export interface TariffView {
  version: number;
  currency: string;
  destinations: CallDestination[];
}

export interface CallingView {
  native_available: boolean;
  native_unavailable_reason: string | null;
  internet_dialer_enabled: boolean;
  internet_dialer_reason: string | null;
  requires_line_selection: boolean;
}

export interface LineSummary {
  entitlement_id: string;
  order_id: string;
  order_reference: string;
  product_name: string;
  delivery: LineDelivery;
  number_status: NumberStatus;
  e164: string | null;
  activation_state: string | null;
  installation_state: string | null;
  ready_to_use: boolean;
  expires_at: string | null;
  expired: boolean;
}

export interface LineDetail {
  entitlement_id: string;
  order_id: string;
  order_reference: string;
  order_item_id: string;
  product_id: string;
  product_name: string;
  delivery: LineDelivery;
  ready_to_use: boolean;
  number_status: NumberStatus;
  assigned_number: AssignedNumber | null;
  installation: InstallationView | null;
  line: LineStateView | null;
  usage: UsageView;
  restriction: RestrictionView | null;
  top_ups: TopUpView;
  tariff: TariffView | null;
  calling: CallingView;
}

export interface InstallationGrant {
  grant_token: string;
  expires_at: string;
  one_time_use: boolean;
  delivery_count: number;
}

export interface InstallationCredential {
  entitlement_id: string;
  /** `LPA:1$…` — the whole secret. Never logged, never persisted. */
  lpa: string;
  one_time_use: boolean;
  delivery_count: number;
  reinstall_available: boolean;
}

export function listLines(accessToken: string): Promise<{ lines: LineSummary[] }> {
  return apiRequest<{ lines: LineSummary[] }>('/me/lines', { accessToken });
}

export function getLine(
  accessToken: string,
  entitlementId: string,
): Promise<LineDetail> {
  return apiRequest<LineDetail>(`/me/lines/${entitlementId}`, { accessToken });
}

/**
 * Authorize one delivery. Safe to call again; returns no profile.
 *
 * The split is the point: this half is retryable and the next half is not, so a
 * customer who taps twice mints two grants and spends one rather than spending
 * a one-time profile on the first tap.
 */
export function requestInstallationGrant(
  accessToken: string,
  entitlementId: string,
): Promise<InstallationGrant> {
  return apiRequest<InstallationGrant>(
    `/me/lines/${entitlementId}/installation/grant`,
    { method: 'POST', accessToken },
  );
}

/** Spend the grant. **Not** safe to call twice — the second call is refused. */
export function redeemInstallationGrant(
  accessToken: string,
  entitlementId: string,
  grantToken: string,
): Promise<InstallationCredential> {
  return apiRequest<InstallationCredential>(
    `/me/lines/${entitlementId}/installation/redeem`,
    { method: 'POST', accessToken, body: { grant_token: grantToken } },
  );
}

export function confirmInstallation(
  accessToken: string,
  entitlementId: string,
  installed: boolean,
): Promise<LineDetail> {
  return apiRequest<LineDetail>(
    `/me/lines/${entitlementId}/installation/confirm`,
    { method: 'POST', accessToken, body: { installed } },
  );
}

/**
 * Split `LPA:1$<SM-DP+ address>$<activation code>` into its typed parts.
 *
 * Needed because manual entry is two separate fields on both iOS and Android,
 * and a customer copying the whole string into the first one gets a failure that
 * looks like a bad profile. Returns `null` rather than guessing when the shape
 * is not the documented one — a wrong split is worse than offering the whole
 * string to copy.
 */
export function splitActivationCode(
  lpa: string,
): { smdpAddress: string; activationCode: string } | null {
  const parts = lpa.split('$');
  if (parts.length < 3 || !parts[0].startsWith('LPA:')) {
    return null;
  }
  const [, smdpAddress, activationCode] = parts;
  if (!smdpAddress || !activationCode) {
    return null;
  }
  return { smdpAddress, activationCode };
}
