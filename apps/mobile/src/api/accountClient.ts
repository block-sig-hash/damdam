import { apiRequest } from './http';

/**
 * Mirrors apps/api/app/account/schemas.py (US-38, chunk 21).
 *
 * Two shapes here carry meaning that a client must not flatten.
 *
 * `DeletionPreflight.blockers` is a **list of reasons**, each with a stable
 * `code` this app localizes. Rendering it as "you cannot delete your account"
 * throws away the only part the customer can act on, and the server
 * deliberately does not send the internal detail — that text can name another
 * member's line.
 *
 * `NotificationPreference` rows are only what has been **decided**. An empty
 * list is a new account, not "everything is off": the absent row is a default
 * and an explicit `false` is a decision, and a settings screen that cannot tell
 * them apart will eventually save a default back as a decision.
 */

export type SessionPlatform = 'ios' | 'android' | 'web' | 'unknown';

export interface DeviceSession {
  session_id: string;
  platform: SessionPlatform;
  device_label: string | null;
  app_version: string | null;
  last_seen_city: string | null;
  last_seen_country: string | null;
  last_seen_at: string | null;
  /** Set once this device is signed out. The row stays so it can be shown. */
  revoked_at: string | null;
}

export interface ReceiptLine {
  description: string;
  quantity: number;
  /** A string, always. A price that travels as a float comes back different. */
  unit_amount: string;
  total_amount: string;
}

export interface Receipt {
  order_id: string;
  reference: string;
  placed_at: string;
  currency: string;
  total_amount: string;
  payment_state: string;
  lines: ReceiptLine[];
  organization_id: string | null;
}

export type SupportCategory =
  | 'installation'
  | 'connectivity'
  | 'billing'
  | 'refund'
  | 'account'
  | 'other';

export interface SupportRequest {
  request_id: string;
  reference: string;
  category: SupportCategory;
  state: string;
  subject: string;
  created_at: string;
  order_id: string | null;
  entitlement_id: string | null;
  subject_summary: string | null;
}

export type NotificationCategory = 'low_balance' | 'expiry' | 'order_status';
export type NotificationChannel = 'push' | 'email' | 'sms';

export interface NotificationPreference {
  category: NotificationCategory;
  channel: NotificationChannel;
  enabled: boolean;
}

export interface DeletionBlocker {
  kind: string;
  /** What the app localizes. There is no free text to render. */
  code: string;
  amount: string | null;
  currency: string | null;
}

export interface DeletionPreflight {
  may_delete: boolean;
  blockers: DeletionBlocker[];
}

export interface ExportJob {
  export_id: string;
  state: string;
  requested_at: string;
  completed_at: string | null;
  expires_at: string | null;
}

export function fetchSessions(accessToken: string): Promise<{ sessions: DeviceSession[] }> {
  return apiRequest<{ sessions: DeviceSession[] }>('/me/sessions', { accessToken });
}

export function revokeSession(accessToken: string, sessionId: string): Promise<void> {
  return apiRequest<void>(`/me/sessions/${sessionId}`, {
    method: 'DELETE',
    accessToken,
  });
}

/**
 * Sign every device out, sparing at most the one named.
 *
 * `keepSessionId` is omitted when the customer has confirmed they mean this
 * device too — the stolen-phone case, where staying signed in here is the wrong
 * outcome.
 */
export function revokeAllSessions(
  accessToken: string,
  keepSessionId?: string,
): Promise<{ revoked: number }> {
  return apiRequest<{ revoked: number }>('/me/sessions/revoke-all', {
    method: 'POST',
    accessToken,
    body: keepSessionId ? { keep_session_id: keepSessionId } : {},
  });
}

export function fetchReceipts(accessToken: string): Promise<{ receipts: Receipt[] }> {
  return apiRequest<{ receipts: Receipt[] }>('/me/receipts', { accessToken });
}

export function fetchReceipt(accessToken: string, orderId: string): Promise<Receipt> {
  return apiRequest<Receipt>(`/me/receipts/${orderId}`, { accessToken });
}

export function fetchSupportRequests(
  accessToken: string,
): Promise<{ requests: SupportRequest[] }> {
  return apiRequest<{ requests: SupportRequest[] }>('/me/support-requests', {
    accessToken,
  });
}

export function openSupportRequest(
  accessToken: string,
  input: {
    category: SupportCategory;
    subject: string;
    body: string;
    orderId?: string;
    entitlementId?: string;
  },
): Promise<SupportRequest> {
  return apiRequest<SupportRequest>('/me/support-requests', {
    method: 'POST',
    accessToken,
    body: {
      category: input.category,
      subject: input.subject,
      body: input.body,
      ...(input.orderId ? { order_id: input.orderId } : {}),
      ...(input.entitlementId ? { entitlement_id: input.entitlementId } : {}),
    },
  });
}

export function fetchPreferences(
  accessToken: string,
): Promise<{ preferences: NotificationPreference[] }> {
  return apiRequest<{ preferences: NotificationPreference[] }>(
    '/me/notification-preferences',
    { accessToken },
  );
}

export function setPreference(
  accessToken: string,
  preference: NotificationPreference,
): Promise<NotificationPreference> {
  return apiRequest<NotificationPreference>('/me/notification-preferences', {
    method: 'PUT',
    accessToken,
    body: preference,
  });
}

export function fetchDeletionPreflight(
  accessToken: string,
): Promise<DeletionPreflight> {
  return apiRequest<DeletionPreflight>('/me/account/deletion-preflight', {
    accessToken,
  });
}

export function requestExport(accessToken: string): Promise<ExportJob> {
  return apiRequest<ExportJob>('/me/account/export', {
    method: 'POST',
    accessToken,
  });
}

/**
 * Whether a category and channel is on, given only what has been decided.
 *
 * The default lives here rather than in a screen because two screens with two
 * copies of a default eventually disagree, and the one that is wrong is the one
 * that saves.
 */
export function isEnabled(
  preferences: NotificationPreference[],
  category: NotificationCategory,
  channel: NotificationChannel,
): boolean {
  const decided = preferences.find(
    preference => preference.category === category && preference.channel === channel,
  );
  return decided ? decided.enabled : true;
}
