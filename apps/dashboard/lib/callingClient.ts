import { clientMessage, localeHeader } from "./clientI18n";
import { readConsumerSession } from "./consumerSession";

/**
 * The browser client for V02/V03's calling contract (US-48, chunk V05).
 *
 * Three properties matter more than the shapes.
 *
 * **It reads only the consumer token.** Not the operator token, not the admin
 * token. An internal user who opens the calling area is signed out, not
 * elevated. See `consumerSession.ts`.
 *
 * **No provider material crosses this boundary except one short-lived token.**
 * `issueClientSession` returns a per-device grant with its own expiry, and it
 * is the only response in the contract that carries anything credential-shaped.
 * There is no Telnyx API key and no SIP password in this app, in its bundle, or
 * in anything it stores — the account key never leaves the server.
 *
 * **Amounts stay strings.** They are exact decimals on the wire and are only
 * ever displayed. Parsing one into a float to render it is how a rate becomes
 * wrong in its fourth decimal place.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/v1";

export type AttemptState =
  | "authorized"
  | "dialing"
  | "ringing"
  | "answered"
  | "ended"
  | "failed"
  | "expired";

export type ChargeView = {
  amount: string;
  currency: string;
  billable_seconds: number;
  setup_amount: string;
  usage_amount: string;
  /** False means the supplier's record could still move this. Not a final bill. */
  is_final: boolean;
  settled_at: string | null;
};

export type AttemptView = {
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
  /** Null while live or while settlement is deferred. Never rendered as zero. */
  charge: ChargeView | null;
};

export type EligibilityView = {
  destination_e164: string;
  destination_country: string;
  destination_kind: string;
  /** Chosen by the server; the browser displays but never nominates it. */
  identity_e164: string;
  currency: string;
  max_seconds: number;
  max_charge_amount: string;
  rate_per_minute_amount: string;
  setup_amount: string;
  available_amount: string;
  fundable: boolean;
  route_enabled: boolean;
};

export type ClientSessionView = {
  token: string;
  sip_identity: string;
  expires_at: string;
};

export type StartInstruction = {
  attempt_id: string;
  destination_e164: string;
  correlation: string;
  max_seconds: number;
  expires_at: string;
};

export class CallingApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "CallingApiError";
    this.code = code;
    this.status = status;
  }
}

function consumerHeaders(accessToken?: string): HeadersInit {
  const token = accessToken ?? readConsumerSession()?.accessToken;
  if (!token) {
    throw new CallingApiError(
      "unauthenticated",
      clientMessage("common.errors.signInRequired"),
      401,
    );
  }
  return { Authorization: `Bearer ${token}`, ...localeHeader() };
}

async function callingRequest<T>(
  path: string,
  init: {
    method?: string;
    body?: unknown;
    idempotencyKey?: string;
    accessToken?: string;
  } = {},
): Promise<T> {
  const { method = "GET", body, idempotencyKey, accessToken } = init;
  const headers: Record<string, string> = {
    ...(consumerHeaders(accessToken) as Record<string, string>),
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      // The API is a separate origin and authorizes by bearer token, so no
      // cookie is sent and there is no CSRF surface to defend here. Saying so
      // explicitly: `omit` is a decision, not a default left unexamined.
      credentials: "omit",
    });
  } catch {
    throw new CallingApiError(
      "network_error",
      clientMessage("common.errors.generic"),
      0,
    );
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      error?: string;
      message?: string;
    };
    throw new CallingApiError(
      payload.error ?? String(response.status),
      payload.message ?? clientMessage("common.errors.generic"),
      response.status,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function getEligibility(params: {
  destination: string;
  currency: string;
}): Promise<EligibilityView> {
  const query = new URLSearchParams({
    destination: params.destination,
    currency: params.currency,
  });
  return callingRequest<EligibilityView>(`/calls/eligibility?${query.toString()}`);
}

export async function issueClientSession(
  deviceId: string,
  deviceLabel?: string,
  accessToken?: string,
): Promise<ClientSessionView> {
  return callingRequest<ClientSessionView>("/calls/client-session", {
    method: "POST",
    body: { device_id: deviceId, device_label: deviceLabel ?? null },
    accessToken,
  });
}

export async function revokeClientSession(deviceId: string): Promise<void> {
  await callingRequest<void>(
    `/calls/client-session?device_id=${encodeURIComponent(deviceId)}`,
    { method: "DELETE" },
  );
}

export async function authorizeCall(params: {
  destination: string;
  idempotencyKey: string;
  currency: string;
  deviceId: string;
  accessToken?: string;
}): Promise<AttemptView> {
  return callingRequest<AttemptView>("/calls/authorize", {
    method: "POST",
    idempotencyKey: params.idempotencyKey,
    accessToken: params.accessToken,
    body: {
      destination: params.destination,
      idempotency_key: params.idempotencyKey,
      currency: params.currency,
      // Personal calling only. This area has no organization payer by design:
      // a member's work calls belong on a surface their employer can see, and
      // that is not this one.
      organization_id: null,
      device_id: params.deviceId,
      requested_seconds: null,
    },
  });
}

export async function startCall(
  attemptId: string,
  deviceId: string,
  accessToken?: string,
): Promise<StartInstruction> {
  return callingRequest<StartInstruction>(
    `/calls/${attemptId}/start?device_id=${encodeURIComponent(deviceId)}`,
    { method: "POST", accessToken },
  );
}

export async function stopCall(
  attemptId: string,
  reason?: string,
  accessToken?: string,
): Promise<AttemptView> {
  return callingRequest<AttemptView>(`/calls/${attemptId}/stop`, {
    method: "POST",
    body: { reason: reason ?? null },
    accessToken,
  });
}

export async function getCall(
  attemptId: string,
  accessToken?: string,
): Promise<AttemptView> {
  return callingRequest<AttemptView>(`/calls/${attemptId}`, { accessToken });
}

export async function listCalls(limit = 20): Promise<AttemptView[]> {
  const response = await callingRequest<{ attempts: AttemptView[] }>(
    `/calls?limit=${limit}`,
  );
  return response.attempts;
}
