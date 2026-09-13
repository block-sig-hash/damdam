import { clientMessage, localeHeader } from "./clientI18n";
import { writeConsumerSession } from "./consumerSession";

/**
 * Consumer sign-in for the browser calling area (US-48, chunk V05).
 *
 * Uses chunk 06's **email identity** path — request a code, prove control of
 * the mailbox, receive a token — rather than the operator password login this
 * app already has. Two reasons, and the second is the important one:
 *
 * 1. A consumer account has no password. Chunk 06 deliberately built identity
 *    around proving control of an identifier.
 * 2. It cannot be satisfied by an operator or admin credential. Somebody with
 *    staff access who wants to place a personal call has to sign in as
 *    themselves, which is exactly the separation the assignment asks for.
 *
 * The request step answers identically whether or not an account exists, which
 * is chunk 06's rule and not this chunk's to relax: a differing response turns
 * this form into an account-existence oracle.
 */

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/v1";

type AuthResponse = {
  access_token: string;
  refresh_token: string;
  user: { id: string };
  is_new_user: boolean;
};

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...localeHeader() },
    body: JSON.stringify(body),
    credentials: "omit",
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as {
      message?: string;
    };
    throw new Error(payload.message ?? clientMessage("common.errors.generic"));
  }
  return (await response.json()) as T;
}

export async function requestConsumerSignIn(
  email: string,
  locale: "en" | "fr",
): Promise<void> {
  await post<{ message: string }>("/auth/email/login/request", { email, locale });
}

/**
 * Exchange the emailed token for a session.
 *
 * The refresh token is deliberately **not stored**. This area is short-lived by
 * design — a calling credential on a shared machine should expire with the tab,
 * not be silently renewable — and a refresh token in browser storage is the
 * thing that would make it renewable.
 */
export async function confirmConsumerSignIn(token: string): Promise<void> {
  const result = await post<AuthResponse>("/auth/email/login/confirm", { token });
  writeConsumerSession({
    accessToken: result.access_token,
    userId: result.user.id,
  });
}
