import { API_BASE_URL } from '../config/env';
import { i18n, localeHeader } from '../i18n';

/**
 * One request helper for the consumer surface (chunk 18 onward).
 *
 * The older clients each re-implement fetch, error parsing and locale headers,
 * and each one translates the server's error code into a slightly different
 * message. That is survivable for six endpoints and not for the consumer
 * journey, where the same `order_not_found` has to read the same way whether it
 * surfaced from checkout, My Line or a receipt.
 *
 * What this deliberately does *not* do is retry. A GET is safe to retry and a
 * POST is not — `POST /orders` twice is two orders — so the decision belongs to
 * the caller that knows which it is, not to a helper that sees only a path.
 */

export type ApiErrorCode =
  | 'network_error'
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'rate_limited'
  | 'server_error'
  | 'validation_error'
  | string;

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly retryAfter?: number;

  constructor(code: ApiErrorCode, message: string, status: number, retryAfter?: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.retryAfter = retryAfter;
  }

  /**
   * True when the caller's credential is the problem, not the request.
   *
   * The session layer needs this to decide between "sign in again" and "try
   * again", and callers must not infer it from the code string: the server
   * sends a different code for an expired token than for a revoked one.
   */
  get isAuthFailure(): boolean {
    return this.status === 401;
  }

  /** True when retrying the identical request could plausibly succeed. */
  get isTransient(): boolean {
    return this.code === 'network_error' || this.status >= 500 || this.status === 429;
  }
}

interface ErrorPayload {
  error?: string;
  message?: string;
  details?: { retry_after?: number };
}

function codeForStatus(status: number): ApiErrorCode {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server_error';
  return 'validation_error';
}

async function toApiError(response: Response): Promise<ApiError> {
  let payload: ErrorPayload = {};
  try {
    payload = (await response.json()) as ErrorPayload;
  } catch {
    // A body that is not JSON is still a real failure. Falling through with an
    // empty payload keeps the status, which is the part that decides what the
    // app does next.
  }
  return new ApiError(
    payload.error ?? codeForStatus(response.status),
    // The server localizes its own messages from the Accept-Language header the
    // request carried, so its text is preferred over anything invented here.
    payload.message ?? i18n.t('errors.generic', { ns: 'auth' }),
    response.status,
    payload.details?.retry_after,
  );
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  accessToken?: string;
  body?: unknown;
  /**
   * Sent as `Idempotency-Key`. Required by anything that creates or moves
   * money; see chunk 19's checkout, which generates one per attempt and reuses
   * it across retries so a lost response cannot become a second order.
   */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = 'GET', accessToken, body, idempotencyKey, signal } = options;
  const headers: Record<string, string> = { ...localeHeader() };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch {
    throw new ApiError(
      'network_error',
      i18n.t('errors.network', { ns: 'auth' }),
      0,
    );
  }

  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
