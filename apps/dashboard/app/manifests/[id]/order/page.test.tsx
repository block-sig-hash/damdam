import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ManifestOrderPage from "./page";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "manifest-1" }) }));

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

const pilgrims = [
  { id: "p1", name: "Aisha Bello", phone_number: "+234801", family_group_id: null },
  { id: "p2", name: "Musa Garba", phone_number: "+234802", family_group_id: null },
];
const basic = {
  id: "basic",
  name: "Basic",
  retail_price_ngn: 160000,
  wholesale_price_ngn: 128000,
  estimated_margin_ngn: 32000,
  is_group_tier: false,
  min_group_size: null,
  max_group_size: null,
};
const family = {
  ...basic,
  id: "family",
  name: "Family",
  retail_price_ngn: 240000,
  wholesale_price_ngn: 176000,
  estimated_margin_ngn: 64000,
  is_group_tier: true,
  min_group_size: 2,
  max_group_size: 8,
};

describe("HTO manifest orders", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("AC-06.1/2/3/6 selects a subset and shows wholesale total and margin", async () => {
    window.localStorage.setItem("hto_access_token", "operator-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ pilgrims }))
      .mockResolvedValueOnce(response({ tiers: [basic, family] }))
      .mockResolvedValueOnce(response({ orders: [] }))
      .mockResolvedValueOnce(response({ manifest_order_id: "order-1", total_ngn: 256000, invoice_url: "/invoice" }))
      .mockResolvedValueOnce(response({ pilgrims: [] }))
      .mockResolvedValueOnce(response({ tiers: [basic, family] }))
      .mockResolvedValueOnce(response({ orders: [{ id: "order-1", tier_name: "Basic", pilgrim_count: 2, total_ngn: 256000, status: "awaiting_payment" }] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ManifestOrderPage />);

    const orderSection = (await screen.findByText("2. Select pilgrims")).closest("section")!;
    const boxes = within(orderSection).getAllByRole("checkbox");
    fireEvent.click(boxes[0]);
    fireEvent.click(boxes[1]);

    expect(screen.getByText("₦128,000 per pilgrim")).toBeInTheDocument();
    expect(screen.getByText("Total ₦256,000")).toBeInTheDocument();
    expect(screen.getByText("Estimated retail margin ₦64,000")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Place order and generate invoice" }));

    expect(await screen.findByText("Order awaiting bank-transfer payment")).toBeInTheDocument();
    const request = fetchMock.mock.calls[3][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      pricing_tier_id: "basic",
      manifest_pilgrim_ids: ["p1", "p2"],
    });
  });

  it("AC-06.1 locks a complete pre-grouped selection to the Family tier", async () => {
    window.localStorage.setItem("hto_access_token", "operator-token");
    const grouped = pilgrims.map((pilgrim) => ({ ...pilgrim, family_group_id: "group-1" }));
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(response({ pilgrims: grouped }))
        .mockResolvedValueOnce(response({ tiers: [basic, family] }))
        .mockResolvedValueOnce(response({ orders: [] })),
    );
    render(<ManifestOrderPage />);

    const orderSection = (await screen.findByText("2. Select pilgrims")).closest("section")!;
    fireEvent.click(within(orderSection).getAllByRole("checkbox")[0]);
    await waitFor(() => expect(within(orderSection).getAllByRole("checkbox").every((box) => (box as HTMLInputElement).checked)).toBe(true));
    expect(screen.getByText("₦176,000 per pilgrim")).toBeInTheDocument();
    expect(screen.queryByText("₦128,000 per pilgrim")).not.toBeInTheDocument();
  });
});
