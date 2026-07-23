import { cleanup, fireEvent, render, screen, waitFor } from "@/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import AdminHTOOperatorsPage from "./page";

function response(body: unknown) {
  return { ok: true, json: vi.fn().mockResolvedValue(body) };
}

const OPERATOR = {
  id: "operator-1",
  business_name: "Barakah Hajj Services",
  operator_name: "Amina Yusuf",
  email: "amina@example.com",
  phone_number: "+2348012345678",
  nahcon_licence_number: "NAHCON-1",
  email_verified: true,
  approval_status: "pending" as const,
  created_at: "2026-07-14T00:00:00Z",
};

describe("admin HTO operator approvals", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("AC-04.4: approves a pending operator after confirmation", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ operators: [OPERATOR] }))
      .mockResolvedValueOnce(response({ approval_status: "approved" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    render(<AdminHTOOperatorsPage />);

    expect(await screen.findByText("Barakah Hajj Services")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toContain("/admin/hto-operators/operator-1/approve");
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("Barakah Hajj Services"));
    // fetchMock having been called twice only means the approve request
    // was sent, not that its response has resolved and the resulting
    // setOperators(...) state update has re-rendered yet — wait for the
    // actual DOM consequence, not just the intermediate call count.
    await waitFor(() =>
      expect(screen.queryByText("Barakah Hajj Services")).not.toBeInTheDocument(),
    );
  });

  it("rejects a pending operator with a required reason", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ operators: [OPERATOR] }))
      .mockResolvedValueOnce(response({ approval_status: "rejected" }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    render(<AdminHTOOperatorsPage />);

    expect(await screen.findByText("Barakah Hajj Services")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByLabelText("Rejection reason"), {
      target: { value: "Licence number could not be verified" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm reject" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [, rejectCall] = fetchMock.mock.calls;
    expect(rejectCall[0]).toContain("/admin/hto-operators/operator-1/reject");
    expect(JSON.parse(String(rejectCall[1].body))).toEqual({
      reason: "Licence number could not be verified",
    });
    await waitFor(() =>
      expect(screen.queryByText("Barakah Hajj Services")).not.toBeInTheDocument(),
    );
  });

  it("does not submit a rejection without a reason", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ operators: [OPERATOR] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminHTOOperatorsPage />);

    expect(await screen.findByText("Barakah Hajj Services")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm reject" }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Enter a reason for rejecting this operator.")).toBeInTheDocument();
  });

  it("switches status filters and reloads the list", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(response({ operators: [OPERATOR] }))
      .mockResolvedValueOnce(response({ operators: [] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminHTOOperatorsPage />);

    expect(await screen.findByText("Barakah Hajj Services")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approved" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toContain("status=approved");
    expect(await screen.findByText("No approved operators.")).toBeInTheDocument();
  });
});
