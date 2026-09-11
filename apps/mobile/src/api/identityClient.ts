import type { AuthResponse } from './authClient';
import { apiRequest } from './http';

/**
 * The email identity endpoints chunk 06 built (`/v1/auth/email/**`).
 *
 * Two things about this contract shape the screens that use it:
 *
 * **The same response comes back whether or not the address has an account.**
 * That is deliberate on the server (AC-29: no pre-verification enumeration), so
 * the app must not draw a "welcome back" or "create your account" screen from
 * the request step. It finds out which happened at *confirm* time, from
 * `is_new_user`.
 *
 * **Login and recovery are different tokens for different things.** Proving you
 * can read a mailbox authenticates you; taking over an account whose other
 * sessions must be revoked is `recovery`, and the server refuses to accept one
 * where the other is expected. The app keeps them on separate screens for the
 * same reason.
 */

export interface IdentityMessage {
  message: string;
}

export interface RecoverySession {
  access_token: string;
  refresh_token: string;
  user: AuthResponse['user'];
}

export function requestEmailLogin(
  email: string,
  locale: 'en' | 'fr' = 'en',
): Promise<IdentityMessage> {
  return apiRequest<IdentityMessage>('/auth/email/login/request', {
    method: 'POST',
    body: { email, locale },
  });
}

export function confirmEmailLogin(token: string): Promise<AuthResponse> {
  return apiRequest<AuthResponse>('/auth/email/login/confirm', {
    method: 'POST',
    body: { token },
  });
}

export function requestEmailRecovery(
  email: string,
  locale: 'en' | 'fr' = 'en',
): Promise<IdentityMessage> {
  // The locale travels in the body, not only in the header: the message is
  // composed now and read later, so the language has to be the one the customer
  // chose rather than the one whatever request happens to trigger a resend used.
  return apiRequest<IdentityMessage>('/auth/email/recovery/request', {
    method: 'POST',
    body: { email, locale },
  });
}

export function confirmEmailRecovery(token: string): Promise<RecoverySession> {
  return apiRequest<RecoverySession>('/auth/email/recovery/confirm', {
    method: 'POST',
    body: { token },
  });
}

export function requestEmailVerification(
  accessToken: string,
  email: string,
  locale: 'en' | 'fr' = 'en',
): Promise<IdentityMessage> {
  return apiRequest<IdentityMessage>('/auth/email/verify/request', {
    method: 'POST',
    accessToken,
    body: { email, locale },
  });
}

export function confirmEmailVerification(token: string): Promise<IdentityMessage> {
  return apiRequest<IdentityMessage>('/auth/email/verify/confirm', {
    method: 'POST',
    body: { token },
  });
}
