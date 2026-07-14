import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminPricingTiersPage from "./page";

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

describe("admin Naira pricing", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("AC-26.1/2/3/4: shows current price, confirms the % change, and updates immediately", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ tiers: [{
        id: "tier-1",
        name: "Basic",
        ngn_price: 160000,
        is_group_tier: false,
      }] }))
      .mockResolvedValueOnce(response({
        id: "tier-1",
        name: "Basic",
        old_ngn_price: 160000,
        new_ngn_price: 176000,
        percent_change: 10,
        changed_at: "2026-07-14T00:00:00Z",
      }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    render(<AdminPricingTiersPage />);

    expect(await screen.findByText("Basic")).toBeInTheDocument();
    expect(screen.getByText("₦160,000")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("New price (₦)"), { target: { value: "176000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("10.0% increase"));
    const [, patchCall] = fetchMock.mock.calls;
    expect(patchCall[0]).toContain("/admin/pricing-tiers/tier-1");
    expect(patchCall[1]).toMatchObject({ method: "PATCH" });
    expect(await screen.findByText("₦176,000")).toBeInTheDocument();
  });

  it("does not submit the price change when the admin cancels the confirmation", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ tiers: [{
      id: "tier-1",
      name: "Basic",
      ngn_price: 160000,
      is_group_tier: false,
    }] }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));
    render(<AdminPricingTiersPage />);

    expect(await screen.findByText("Basic")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("New price (₦)"), { target: { value: "176000" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("New price (₦)")).toBeInTheDocument();
  });
});
