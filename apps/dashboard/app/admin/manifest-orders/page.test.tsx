import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminManifestOrdersPage from "./page";

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

describe("admin manifest payment confirmation", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("AC-06.5 requires explicit confirmation before provisioning", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ orders: [{
        id: "order-1",
        hto_business_name: "Barakah Hajj",
        manifest_name: "Flight NAF203",
        pilgrim_count: 4,
        total_ngn: 512000,
        invoice_url: "/invoice",
        days_pending: 3,
      }] }))
      .mockResolvedValueOnce(response({ status: "provisioning" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    render(<AdminManifestOrdersPage />);

    expect(await screen.findByText("Barakah Hajj")).toBeInTheDocument();
    expect(screen.getByText("3 days pending").closest("article")).toHaveClass("overdue");
    fireEvent.click(screen.getByRole("button", { name: "Confirm payment received" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("cannot be undone"));
    expect(screen.queryByText("Barakah Hajj")).not.toBeInTheDocument();
  });
});
