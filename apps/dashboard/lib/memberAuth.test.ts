import { afterEach, describe, expect, it, vi } from "vitest";

import { completeMemberLogin, requestMemberLogin } from "./memberAuth";

function response(body: unknown, ok = true): Response {
  return {
    ok,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

describe("enterprise member authentication", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("requests a localized passwordless email link", async () => {
    window.localStorage.setItem("damdam_locale", "fr");
    const fetchMock = vi.fn().mockResolvedValue(response({ message: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await requestMemberLogin("admin@example.test");

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/auth/email/login/request"),
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Accept-Language": "fr" }),
        body: JSON.stringify({ email: "admin@example.test", locale: "fr" }),
      }),
    );
  });

  it("stores the member session and selects an administrable organization", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          access_token: "access-token",
          refresh_token: "refresh-token",
          user: { locale: "en" },
        }),
      )
      .mockResolvedValueOnce(
        response({
          organizations: [
            { id: "org-member", name: "Member org", role: "member" },
            { id: "org-admin", name: "Admin org", role: "administrator" },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await completeMemberLogin("magic-token");

    expect(window.localStorage.getItem("member_access_token")).toBe(
      "access-token",
    );
    expect(window.localStorage.getItem("member_refresh_token")).toBe(
      "refresh-token",
    );
    expect(window.localStorage.getItem("damdam_organization_id")).toBe(
      "org-admin",
    );
    expect(fetchMock.mock.calls[1][1]).toEqual(
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer access-token",
        }),
      }),
    );
  });

  it("clears the new session when the account cannot administer an organization", async () => {
    window.localStorage.setItem("member_access_token", "old-access-token");
    window.localStorage.setItem("member_refresh_token", "old-refresh-token");
    window.localStorage.setItem("damdam_organization_id", "old-org");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        response({
          access_token: "access-token",
          refresh_token: "refresh-token",
          user: { locale: "en" },
        }),
      )
      .mockResolvedValueOnce(
        response({
          organizations: [
            { id: "org-billing", name: "Billing org", role: "billing" },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(completeMemberLogin("magic-token")).rejects.toThrow(
      "administrator",
    );

    expect(window.localStorage.getItem("member_access_token")).toBeNull();
    expect(window.localStorage.getItem("member_refresh_token")).toBeNull();
    expect(window.localStorage.getItem("damdam_organization_id")).toBeNull();
  });
});
