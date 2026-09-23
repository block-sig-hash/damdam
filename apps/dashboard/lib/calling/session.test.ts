import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserCallSession } from "./session";
import { CallAdapterError, type CallClientAdapter } from "./adapter";
import { CallingApiError, type AttemptView } from "../callingClient";
import {
  clearConsumerSession,
  readActiveCall,
  rememberActiveCall,
  writeConsumerSession,
} from "../consumerSession";

vi.mock("../callingClient", async () => {
  const actual = await vi.importActual<typeof import("../callingClient")>(
    "../callingClient",
  );
  return {
    ...actual,
    getEligibility: vi.fn(),
    issueClientSession: vi.fn(),
    authorizeCall: vi.fn(),
    startCall: vi.fn(),
    stopCall: vi.fn(),
    getCall: vi.fn(),
    listCalls: vi.fn(),
  };
});

const client = await import("../callingClient");
const authorizeCall = vi.mocked(client.authorizeCall);
const startCall = vi.mocked(client.startCall);
const stopCall = vi.mocked(client.stopCall);
const getCall = vi.mocked(client.getCall);
const issueClientSession = vi.mocked(client.issueClientSession);

const ATTEMPT: AttemptView = {
  attempt_id: "attempt-1",
  state: "authorized",
  destination_e164: "+441632960011",
  destination_country: "GB",
  identity_e164: "+2348000000001",
  currency: "NGN",
  max_seconds: 600,
  max_charge_amount: "1200.00",
  expires_at: "2026-09-13T12:10:00Z",
  created_at: "2026-09-13T12:00:00Z",
  answered_at: null,
  ended_at: null,
  end_reason: null,
  organization_id: null,
  charge: null,
};

class FakeAdapter implements CallClientAdapter {
  readonly name = "fake";
  readonly available = true;
  capabilities = { mute: true, dtmf: true, audioOutput: true };
  digits: string[] = [];
  muted = false;
  hangups = 0;
  private listeners: Array<(event: never) => void> = [];
  private dialFailure: string | null = null;

  failNextDial(code: string) {
    this.dialFailure = code;
  }

  async connect() {}

  async dial() {
    if (this.dialFailure) {
      const code = this.dialFailure;
      this.dialFailure = null;
      throw new CallAdapterError(code);
    }
  }

  async hangup() {
    this.hangups += 1;
  }

  async setMuted(muted: boolean) {
    this.muted = muted;
  }

  async sendDigit(digit: string) {
    this.digits.push(digit);
  }

  subscribe(listener: (event: never) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((entry) => entry !== listener);
    };
  }

  emit(event: unknown) {
    for (const listener of [...this.listeners]) {
      (listener as (value: unknown) => void)(event);
    }
  }

  async disconnect() {
    this.listeners = [];
  }
}

function build(overrides: Partial<ConstructorParameters<typeof BrowserCallSession>[0]> = {}) {
  const adapter = new FakeAdapter();
  const session = new BrowserCallSession({
    accessToken: "token",
    userId: "user-1",
    deviceId: "device-1",
    currency: "NGN",
    adapter,
    requestMicrophone: vi.fn(async () => "granted" as const),
    now: () => 1_000,
    ...overrides,
  });
  return { adapter, session };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  writeConsumerSession({ accessToken: "token", userId: "user-1" });
  authorizeCall.mockResolvedValue(ATTEMPT);
  startCall.mockResolvedValue({
    attempt_id: "attempt-1",
    destination_e164: "+441632960011",
    correlation: "corr-1",
    max_seconds: 600,
    expires_at: "2026-09-13T12:10:00Z",
  });
  stopCall.mockResolvedValue({ ...ATTEMPT, state: "ended", end_reason: "stopped" });
  issueClientSession.mockResolvedValue({
    token: "provider-token",
    sip_identity: "sip:user-1",
    expires_at: "2026-09-13T13:00:00Z",
  });
});

afterEach(() => {
  clearConsumerSession();
});

describe("no accidental paid retries", () => {
  it("AC-48.2: a duplicate click authorizes once", async () => {
    const { session } = build();

    await Promise.all([
      session.place("+441632960011"),
      session.place("+441632960011"),
    ]);

    expect(authorizeCall).toHaveBeenCalledTimes(1);
  });

  it("AC-48.2: a retry after a failure reuses the first idempotency key", async () => {
    const { session } = build();
    authorizeCall.mockRejectedValueOnce(
      new CallingApiError("network_error", "offline", 0),
    );

    await session.place("+441632960011");
    await session.retry();

    const keys = authorizeCall.mock.calls.map(([args]) => args.idempotencyKey);
    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(1);
  });

  it("starts a later completed placement with a fresh idempotency key", async () => {
    const { adapter, session } = build();
    authorizeCall
      .mockResolvedValueOnce(ATTEMPT)
      .mockResolvedValueOnce({ ...ATTEMPT, attempt_id: "attempt-2" });

    await session.place("+441632960011");
    adapter.emit({ kind: "ended", reason: "remote_hangup" });
    await vi.waitFor(() => expect(session.snapshot().phase).toBe("ended"));
    await session.place("+441632960011");

    const keys = authorizeCall.mock.calls.map(([args]) => args.idempotencyKey);
    expect(keys).toHaveLength(2);
    expect(new Set(keys).size).toBe(2);
  });

  it("AC-48.2: a refreshed tab reconciles the live attempt instead of redialing", async () => {
    rememberActiveCall("user-1", "attempt-1");
    getCall.mockResolvedValue({ ...ATTEMPT, state: "answered", answered_at: "2026-09-13T12:00:10Z" });
    const { session } = build();

    await session.reconcile();

    // The durable attempt is the source of truth. Dialling again would be a
    // second call and a second charge for one thing the customer did once.
    expect(getCall).toHaveBeenCalledWith("attempt-1", "token");
    expect(authorizeCall).not.toHaveBeenCalled();
    expect(session.snapshot().phase).toBe("answered");
  });

  it("AC-48.2: reconciling a call that already ended clears it rather than resuming", async () => {
    rememberActiveCall("user-1", "attempt-1");
    getCall.mockResolvedValue({
      ...ATTEMPT,
      state: "ended",
      ended_at: "2026-09-13T12:04:00Z",
      end_reason: "remote_hangup",
    });
    const { session } = build();

    await session.reconcile();

    expect(session.snapshot().phase).toBe("ended");
    expect(readActiveCall("user-1")).toBeNull();
  });

  it("keeps an unknown live attempt recoverable while offline", async () => {
    rememberActiveCall("user-1", "attempt-1");
    getCall.mockRejectedValueOnce(
      new CallingApiError("network_error", "offline", 0),
    );
    const { session } = build();

    await session.reconcile();

    expect(readActiveCall("user-1")).toBe("attempt-1");
    expect(session.snapshot().failureCode).toBe("offline");

    getCall.mockResolvedValueOnce({
      ...ATTEMPT,
      state: "answered",
      answered_at: "2026-09-13T12:00:10Z",
    });
    await session.retry();

    expect(getCall).toHaveBeenCalledTimes(2);
    expect(session.snapshot().phase).toBe("answered");
  });
});

describe("the browser is asked what it can do before money moves", () => {
  it("uses the captured account token and the browser device boundary", async () => {
    const { session } = build();

    await session.place("+441632960011");

    expect(authorizeCall).toHaveBeenCalledWith(
      expect.objectContaining({
        accessToken: "token",
        deviceId: "device-1",
      }),
    );
    expect(issueClientSession).toHaveBeenCalledWith(
      "device-1",
      "browser",
      "token",
    );
    expect(startCall).toHaveBeenCalledWith("attempt-1", "device-1", "token");
  });

  it("AC-48.3: a build with no dialling path never prompts and never authorizes", async () => {
    const requestMicrophone = vi.fn(async () => "granted" as const);
    const adapter = new FakeAdapter();
    Object.defineProperty(adapter, "available", { value: false });
    const { session } = build({ adapter, requestMicrophone });

    await session.place("+441632960011");

    expect(requestMicrophone).not.toHaveBeenCalled();
    expect(authorizeCall).not.toHaveBeenCalled();
    expect(session.snapshot().failureCode).toBe("calling_unavailable");
  });

  it("AC-48.3: microphone denial holds no money", async () => {
    const { session } = build({
      requestMicrophone: vi.fn(async () => "denied" as const),
    });

    await session.place("+441632960011");

    expect(authorizeCall).not.toHaveBeenCalled();
    expect(session.snapshot().failureCode).toBe("microphone_denied");
  });

  it("AC-48.3: a machine with no microphone says so rather than blaming permission", async () => {
    const { session } = build({
      requestMicrophone: vi.fn(async () => "no_device" as const),
    });

    await session.place("+441632960011");

    expect(session.snapshot().failureCode).toBe("no_microphone");
  });
});

describe("an abandoned attempt is always reported", () => {
  it("AC-48.2: a dial that throws stops the attempt on the server", async () => {
    const { adapter, session } = build();
    adapter.failNextDial("sdk_unavailable");

    await session.place("+441632960011");

    expect(stopCall).toHaveBeenCalledWith("attempt-1", expect.any(String), "token");
  });

  it("AC-48.2: closing the tab is best effort and is not the spending control", async () => {
    const { session } = build();
    await session.place("+441632960011");
    stopCall.mockClear();
    stopCall.mockRejectedValueOnce(new CallingApiError("network_error", "gone", 0));

    // A browser being torn down may never finish this request. It must not
    // throw, and the guarantee that the call stops is V03's server-side cutoff,
    // not this.
    await expect(session.releaseOnUnload()).resolves.toBeUndefined();
  });

  it("acknowledges a provider-side end on the server", async () => {
    const { adapter, session } = build();
    await session.place("+441632960011");
    stopCall.mockClear();

    adapter.emit({ kind: "ended", reason: "remote_hangup" });

    await vi.waitFor(() => {
      expect(stopCall).toHaveBeenCalledWith("attempt-1", "remote_hangup", "token");
      expect(session.snapshot().phase).toBe("ended");
    });
  });

  it("hangup enters a terminal phase after stopping the attempt", async () => {
    const { session } = build();
    await session.place("+441632960011");

    await session.hangup();

    expect(session.snapshot().phase).toBe("ended");
    expect(readActiveCall("user-1")).toBeNull();
  });
});

describe("one account's call cannot reach another", () => {
  it("AC-48.1: a disposed session ignores a late provider callback", async () => {
    const { adapter, session } = build();
    await session.place("+441632960011");
    adapter.emit({ kind: "answered" });
    expect(session.snapshot().phase).toBe("answered");

    session.dispose();
    adapter.emit({ kind: "ended", reason: "remote_hangup" });

    expect(session.snapshot().phase).toBe("idle");
    expect(session.snapshot().attemptId).toBeNull();
  });

  it("AC-48.1: signing out removes the remembered call so the next user cannot reconcile it", async () => {
    const { session } = build();
    await session.place("+441632960011");
    expect(readActiveCall("user-1")).toBe("attempt-1");

    clearConsumerSession();

    expect(readActiveCall("user-1")).toBeNull();
    session.dispose();
  });

  it("stops a live attempt when its owner session is disposed", async () => {
    const { session } = build();
    await session.place("+441632960011");
    stopCall.mockClear();

    session.dispose();

    await vi.waitFor(() =>
      expect(stopCall).toHaveBeenCalledWith("attempt-1", "client_disposed", "token"),
    );
  });

  it("releases an authorization that returns after disposal", async () => {
    let resolveAuthorization!: (attempt: AttemptView) => void;
    authorizeCall.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveAuthorization = resolve;
      }),
    );
    const { session } = build();

    const placing = session.place("+441632960011");
    await vi.waitFor(() => expect(authorizeCall).toHaveBeenCalledTimes(1));
    session.dispose();
    clearConsumerSession();
    resolveAuthorization(ATTEMPT);
    await placing;

    expect(stopCall).toHaveBeenCalledWith("attempt-1", "client_disposed", "token");
  });

  it("AC-48.1: an expired session is reported as sign-in, not as a call failure", async () => {
    const { session } = build();
    authorizeCall.mockRejectedValueOnce(
      new CallingApiError("unauthenticated", "expired", 401),
    );

    await session.place("+441632960011");

    expect(session.snapshot().failureCode).toBe("session_expired");
  });
});

describe("in-call controls follow the adapter", () => {
  it("AC-48.3: DTMF is refused rather than dropped when unsupported", async () => {
    const adapter = new FakeAdapter();
    adapter.capabilities = { mute: true, dtmf: false, audioOutput: false };
    const { session } = build({ adapter });
    await session.place("+441632960011");
    adapter.emit({ kind: "answered" });

    await expect(session.sendDigit("5")).resolves.toBe(false);
    expect(adapter.digits).toEqual([]);
  });

  it("AC-48.3: mute reflects the adapter rather than the button", async () => {
    const { adapter, session } = build();
    await session.place("+441632960011");

    await session.setMuted(true);

    expect(adapter.muted).toBe(true);
    expect(session.snapshot().muted).toBe(true);
  });
});
