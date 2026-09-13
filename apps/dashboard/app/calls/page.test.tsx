import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@/test-utils";
import CallsPage from "./page";
import type { AttemptView, EligibilityView } from "@/lib/callingClient";

/**
 * The consumer calling area at the boundary (US-48, AC-48.1 to AC-48.3).
 *
 * The claim being defended is that this page is reachable by a personal
 * account with no organization, and by **nothing else in this app**. The
 * dashboard already holds an operator token and an admin token; neither opens
 * this page, and the tests below assert that by putting those tokens in storage
 * and checking that the visitor is still asked to sign in.
 */

vi.mock("@/lib/callingClient", async () => {
  const actual = await vi.importActual<typeof import("@/lib/callingClient")>(
    "@/lib/callingClient",
  );
  return {
    ...actual,
    getEligibility: vi.fn(),
    listCalls: vi.fn(),
    authorizeCall: vi.fn(),
    startCall: vi.fn(),
    stopCall: vi.fn(),
    getCall: vi.fn(),
    issueClientSession: vi.fn(),
  };
});

vi.mock("@/lib/consumerAuth", () => ({
  requestConsumerSignIn: vi.fn(async () => undefined),
  confirmConsumerSignIn: vi.fn(async () => undefined),
}));

const client = await import("@/lib/callingClient");
const auth = await import("@/lib/consumerAuth");
const getEligibility = vi.mocked(client.getEligibility);
const listCalls = vi.mocked(client.listCalls);
const getCall = vi.mocked(client.getCall);
const authorizeCall = vi.mocked(client.authorizeCall);

const ELIGIBILITY: EligibilityView = {
  destination_e164: "+441632960011",
  destination_country: "GB",
  destination_kind: "fixed",
  currency: "NGN",
  max_seconds: 600,
  max_charge_amount: "1200.00",
  rate_per_minute_amount: "120.00",
  setup_amount: "0.00",
  available_amount: "5000.00",
  fundable: true,
  route_enabled: true,
};

const ATTEMPT: AttemptView = {
  attempt_id: "attempt-1",
  state: "answered",
  destination_e164: "+441632960011",
  destination_country: "GB",
  identity_e164: "+2348000000001",
  currency: "NGN",
  max_seconds: 600,
  max_charge_amount: "1200.00",
  expires_at: "2026-09-13T12:10:00Z",
  created_at: "2026-09-13T12:00:00Z",
  answered_at: "2026-09-13T12:00:10Z",
  ended_at: null,
  end_reason: null,
  organization_id: null,
  charge: null,
};

function signInAsConsumer() {
  window.sessionStorage.setItem("damdam_consumer_access_token", "consumer-token");
  window.sessionStorage.setItem("damdam_consumer_user_id", "user-1");
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  window.localStorage.clear();
  getEligibility.mockResolvedValue(ELIGIBILITY);
  listCalls.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe("AC-48.1 — who can open the calling area", () => {
  it("a personal account with no organization reaches the call surface", async () => {
    signInAsConsumer();

    render(<CallsPage />);

    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());
    // Nothing on this path consulted a membership, an entitlement or a line.
    expect(screen.getByTestId("calls-personal")).toBeTruthy();
  });

  it("an organization operator token does not open it", async () => {
    // The token this app stores after `loginHTO`. It authorizes /home; it must
    // authorize nothing here.
    window.localStorage.setItem("hto_access_token", "operator-token");

    render(<CallsPage />);

    await waitFor(() => expect(screen.getByTestId("calls-email")).toBeTruthy());
    expect(screen.queryByTestId("calls-setup")).toBeNull();
  });

  it("an internal admin token does not open it", async () => {
    window.localStorage.setItem("admin_access_token", "admin-token");

    render(<CallsPage />);

    await waitFor(() => expect(screen.getByTestId("calls-email")).toBeTruthy());
    expect(screen.queryByTestId("calls-setup")).toBeNull();
    expect(listCalls).not.toHaveBeenCalled();
  });

  it("signing out clears the scoped data, including the remembered call", async () => {
    signInAsConsumer();
    window.sessionStorage.setItem(
      "damdam_consumer_active_call:user-1",
      "attempt-1",
    );
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());

    fireEvent.click(screen.getByTestId("calls-sign-out"));

    await waitFor(() => expect(screen.getByTestId("calls-email")).toBeTruthy());
    // Leaving the attempt id behind would let the next person on this browser
    // reconcile — and be shown the cost of — somebody else's call.
    expect(
      window.sessionStorage.getItem("damdam_consumer_active_call:user-1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("damdam_consumer_access_token"),
    ).toBeNull();
  });
});

describe("AC-48.2 — a browser cannot bypass the server's controls", () => {
  it("a reloaded tab reconciles the live attempt instead of dialling again", async () => {
    signInAsConsumer();
    window.sessionStorage.setItem(
      "damdam_consumer_active_call:user-1",
      "attempt-1",
    );
    getCall.mockResolvedValue(ATTEMPT);

    render(<CallsPage />);

    await waitFor(() => expect(getCall).toHaveBeenCalledWith("attempt-1"));
    // The durable attempt is the truth. A second dial would be a second charge
    // for one thing the customer did once.
    expect(authorizeCall).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByTestId("calls-in-progress")).toBeTruthy(),
    );
  });

  it("tells the caller that closing the tab is not what ends the call", async () => {
    signInAsConsumer();
    window.sessionStorage.setItem(
      "damdam_consumer_active_call:user-1",
      "attempt-1",
    );
    getCall.mockResolvedValue(ATTEMPT);

    render(<CallsPage />);

    await waitFor(() =>
      expect(screen.getByTestId("calls-unload-note")).toBeTruthy(),
    );
  });

  it("keeps the call button unusable while the route is switched off", async () => {
    signInAsConsumer();
    getEligibility.mockResolvedValue({ ...ELIGIBILITY, route_enabled: false });
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());

    fireEvent.change(screen.getByTestId("calls-destination"), {
      target: { value: "+441632960011" },
    });

    await waitFor(() =>
      expect(screen.getByTestId("calls-route-disabled")).toBeTruthy(),
    );
    expect(screen.getByTestId("calls-place")).toHaveProperty("disabled", true);
  });

  it("keeps the call button unusable when the balance cannot fund it", async () => {
    signInAsConsumer();
    getEligibility.mockResolvedValue({ ...ELIGIBILITY, fundable: false });
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());

    fireEvent.change(screen.getByTestId("calls-destination"), {
      target: { value: "+441632960011" },
    });

    await waitFor(() =>
      expect(screen.getByTestId("calls-not-fundable")).toBeTruthy(),
    );
    expect(screen.getByTestId("calls-place")).toHaveProperty("disabled", true);
  });
});

describe("AC-48.3 — what the surface says", () => {
  it("prices a destination without committing anything", async () => {
    signInAsConsumer();
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());

    fireEvent.change(screen.getByTestId("calls-destination"), {
      target: { value: "+441632960011" },
    });

    await waitFor(() => expect(screen.getByTestId("calls-rate")).toBeTruthy());
    // Eligibility holds no money and writes no attempt, so editing a number
    // must not move a balance.
    expect(authorizeCall).not.toHaveBeenCalled();
  });

  it("builds a number from the keypad and can correct it", async () => {
    signInAsConsumer();
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());

    fireEvent.click(screen.getByTestId("calls-digit-4"));
    fireEvent.click(screen.getByTestId("calls-digit-4"));
    fireEvent.click(screen.getByTestId("calls-backspace"));

    expect(screen.getByTestId("calls-destination")).toHaveProperty("value", "+4");
  });

  it("never renders a missing cost as zero", async () => {
    signInAsConsumer();
    listCalls.mockResolvedValue([
      {
        ...ATTEMPT,
        attempt_id: "settled",
        state: "ended",
        charge: {
          amount: "480.00",
          currency: "NGN",
          billable_seconds: 240,
          setup_amount: "0.00",
          usage_amount: "480.00",
          is_final: true,
          settled_at: "2026-09-13T12:05:00Z",
        },
      },
      { ...ATTEMPT, attempt_id: "pending", state: "ended", charge: null },
      {
        ...ATTEMPT,
        attempt_id: "unanswered",
        state: "ended",
        answered_at: null,
        charge: null,
      },
    ]);

    render(<CallsPage />);

    await waitFor(() =>
      expect(screen.getByTestId("calls-cost-settled").textContent).toBe(
        "480.00 NGN",
      ),
    );
    expect(screen.getByTestId("calls-cost-pending").textContent).toBe(
      "Cost still being worked out",
    );
    expect(screen.getByTestId("calls-cost-unanswered").textContent).toBe(
      "Not answered",
    );
  });

  it("signs a consumer in by proving control of a mailbox", async () => {
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-email")).toBeTruthy());

    fireEvent.change(screen.getByTestId("calls-email"), {
      target: { value: "someone@example.test" },
    });
    fireEvent.click(screen.getByTestId("calls-send-code"));

    await waitFor(() => expect(screen.getByTestId("calls-code-sent")).toBeTruthy());
    expect(auth.requestConsumerSignIn).toHaveBeenCalledWith(
      "someone@example.test",
      "en",
    );
  });

  it("is reachable by keyboard alone", async () => {
    signInAsConsumer();
    render(<CallsPage />);
    await waitFor(() => expect(screen.getByTestId("calls-setup")).toBeTruthy());

    // Every control is a real button or input, so the tab order reaches all of
    // them. A div with an onClick would pass a click test and fail this one:
    // it would never appear in this query.
    const focusable = document.querySelectorAll("button, input, select, a[href]");
    expect(focusable.length).toBeGreaterThan(12);
    for (const element of focusable) {
      expect(element.getAttribute("tabindex")).not.toBe("-1");
    }
  });
});
