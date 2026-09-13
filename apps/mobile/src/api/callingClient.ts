import { apiRequest } from './http';

/**
 * Mirrors apps/api/app/calling/schemas.py (US-45/US-46, chunks V02 and V03).
 *
 * Two absences in this file are load-bearing and worth reading before the
 * types.
 *
 * **No provider nouns.** There is no call-control id, no connection id and no
 * Telnyx anything, because V01's invariant 7 makes our attempt-to-leg mapping
 * authoritative and provider identifiers mere corroboration. A client that
 * learned one would start correlating on it, and that invariant would quietly
 * stop being true.
 *
 * **No amount is a number.** Money crosses the wire as a decimal string and
 * stays a string here. Parsing `"0.0725"` into a float to render it is how a
 * rate becomes wrong in the fourth decimal place, and the only thing this app
 * does with these values is display them.
 */

export type AttemptState =
  | 'authorized'
  | 'dialing'
  | 'ringing'
  | 'answered'
  | 'ended'
  | 'failed'
  | 'expired';

export interface EligibilityView {
  destination_e164: string;
  destination_country: string;
  destination_kind: string;
  currency: string;
  max_seconds: number;
  /** Decimal strings. See the file note — never parse these to render them. */
  max_charge_amount: string;
  rate_per_minute_amount: string;
  setup_amount: string;
  available_amount: string;
  fundable: boolean;
  /**
   * Reported, never implied. A price with no route is a quote for something
   * that cannot be bought, and a client that cannot tell the difference shows a
   * working call button over a disabled route.
   */
  route_enabled: boolean;
}

export interface ClientSessionView {
  token: string;
  sip_identity: string;
  expires_at: string;
}

export interface ChargeView {
  amount: string;
  currency: string;
  billable_seconds: number;
  setup_amount: string;
  usage_amount: string;
  /**
   * False means the supplier's own record could still move this. A UI that
   * renders a provisional amount as final makes a promise V01 could not
   * establish the basis for.
   */
  is_final: boolean;
  settled_at: string | null;
}

export interface AttemptView {
  attempt_id: string;
  state: AttemptState | string;
  destination_e164: string;
  destination_country: string;
  identity_e164: string;
  currency: string;
  max_seconds: number;
  max_charge_amount: string;
  expires_at: string;
  created_at: string;
  answered_at: string | null;
  ended_at: string | null;
  end_reason: string | null;
  organization_id: string | null;
  /** Null while the call is live or settlement is deferred. Not zero. */
  charge: ChargeView | null;
}

export interface StartInstruction {
  attempt_id: string;
  destination_e164: string;
  /**
   * Echoed back to us by the provider. It *points at* an attempt; it does not
   * authorize one, and the server re-validates ownership from the database
   * before acting on anything it names.
   */
  correlation: string;
  max_seconds: number;
  expires_at: string;
}

interface Auth {
  accessToken: string;
}

export interface EligibilityParams extends Auth {
  destination: string;
  currency: string;
  organizationId?: string | null;
  requestedSeconds?: number;
}

export async function getEligibility({
  accessToken,
  destination,
  currency,
  organizationId,
  requestedSeconds,
}: EligibilityParams): Promise<EligibilityView> {
  const query = new URLSearchParams({ destination, currency });
  if (organizationId) {
    query.set('organization_id', organizationId);
  }
  if (requestedSeconds !== undefined) {
    query.set('requested_seconds', String(requestedSeconds));
  }
  return apiRequest<EligibilityView>(`/v1/calls/eligibility?${query.toString()}`, {
    accessToken,
  });
}

export interface ClientSessionParams extends Auth {
  deviceId: string;
  deviceLabel?: string | null;
}

export async function issueClientSession({
  accessToken,
  deviceId,
  deviceLabel,
}: ClientSessionParams): Promise<ClientSessionView> {
  return apiRequest<ClientSessionView>('/v1/calls/client-session', {
    method: 'POST',
    accessToken,
    body: { device_id: deviceId, device_label: deviceLabel ?? null },
  });
}

export async function revokeClientSession({
  accessToken,
  deviceId,
}: Auth & { deviceId?: string }): Promise<void> {
  const query = deviceId ? `?device_id=${encodeURIComponent(deviceId)}` : '';
  await apiRequest<void>(`/v1/calls/client-session${query}`, {
    method: 'DELETE',
    accessToken,
  });
}

export interface AuthorizeParams extends Auth {
  destination: string;
  /**
   * Generated once per attempt by the caller and reused across retries. A
   * second tap must not become a second hold, and the server keys on this.
   */
  idempotencyKey: string;
  currency: string;
  organizationId?: string | null;
  deviceId?: string | null;
  requestedSeconds?: number;
}

export async function authorizeCall({
  accessToken,
  destination,
  idempotencyKey,
  currency,
  organizationId,
  deviceId,
  requestedSeconds,
}: AuthorizeParams): Promise<AttemptView> {
  return apiRequest<AttemptView>('/v1/calls/authorize', {
    method: 'POST',
    accessToken,
    idempotencyKey,
    body: {
      destination,
      idempotency_key: idempotencyKey,
      currency,
      organization_id: organizationId ?? null,
      device_id: deviceId ?? null,
      requested_seconds: requestedSeconds ?? null,
    },
  });
}

export async function startCall({
  accessToken,
  attemptId,
  deviceId,
}: Auth & { attemptId: string; deviceId?: string | null }): Promise<StartInstruction> {
  const query = deviceId ? `?device_id=${encodeURIComponent(deviceId)}` : '';
  return apiRequest<StartInstruction>(`/v1/calls/${attemptId}/start${query}`, {
    method: 'POST',
    accessToken,
  });
}

export async function stopCall({
  accessToken,
  attemptId,
  reason,
}: Auth & { attemptId: string; reason?: string }): Promise<AttemptView> {
  return apiRequest<AttemptView>(`/v1/calls/${attemptId}/stop`, {
    method: 'POST',
    accessToken,
    body: { reason: reason ?? null },
  });
}

export async function getCall({
  accessToken,
  attemptId,
}: Auth & { attemptId: string }): Promise<AttemptView> {
  return apiRequest<AttemptView>(`/v1/calls/${attemptId}`, { accessToken });
}

export async function listCalls({
  accessToken,
  organizationId,
  limit,
}: Auth & { organizationId?: string | null; limit?: number }): Promise<AttemptView[]> {
  const query = new URLSearchParams();
  if (organizationId) {
    query.set('organization_id', organizationId);
  }
  if (limit !== undefined) {
    query.set('limit', String(limit));
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  const response = await apiRequest<{ attempts: AttemptView[] }>(
    `/v1/calls${suffix}`,
    { accessToken },
  );
  return response.attempts;
}
