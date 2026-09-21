import { clientMessage, localeHeader } from "./clientI18n";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/v1";

type APIError = { message?: string };

type AuthResult = {
  access_token: string;
  refresh_token: string;
  user: { locale: "en" | "fr" };
};

export type MemberOrganization = {
  id: string;
  name: string;
  role: "owner" | "administrator" | "billing" | "member";
};

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as APIError;
    throw new Error(error.message ?? clientMessage("common.errors.generic"));
  }
  return (await response.json()) as T;
}

export async function requestMemberLogin(email: string): Promise<void> {
  const locale =
    window.localStorage.getItem("damdam_locale") === "fr" ? "fr" : "en";
  const response = await fetch(`${API_BASE_URL}/auth/email/login/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...localeHeader() },
    body: JSON.stringify({ email, locale }),
  });
  await parse<{ message: string }>(response);
}

export async function completeMemberLogin(token: string): Promise<void> {
  // Never leave an earlier tenant selected while a new authentication attempt
  // is being resolved. Persist the new session only after its organization has
  // been authorized, so a failed lookup cannot leave a half-signed-in browser.
  window.localStorage.removeItem("member_access_token");
  window.localStorage.removeItem("member_refresh_token");
  window.localStorage.removeItem("damdam_organization_id");
  const response = await fetch(`${API_BASE_URL}/auth/email/login/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...localeHeader() },
    body: JSON.stringify({ token }),
  });
  const auth = await parse<AuthResult>(response);

  const organizationsResponse = await fetch(`${API_BASE_URL}/organizations`, {
    headers: {
      Authorization: `Bearer ${auth.access_token}`,
      "Accept-Language": auth.user.locale,
    },
  });
  const result = await parse<{ organizations: MemberOrganization[] }>(
    organizationsResponse,
  );
  const administrable = result.organizations.find(
    (organization) =>
      organization.role === "owner" || organization.role === "administrator",
  );
  if (!administrable) {
    throw new Error(clientMessage("common.errors.adminRequired"));
  }
  window.localStorage.setItem("member_access_token", auth.access_token);
  window.localStorage.setItem("member_refresh_token", auth.refresh_token);
  window.localStorage.setItem("damdam_locale", auth.user.locale);
  window.localStorage.setItem("damdam_organization_id", administrable.id);
}
