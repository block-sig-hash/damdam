import {
  authorizeCall,
  CallingApiError,
  getCall,
  issueClientSession,
  startCall,
  stopCall,
  type AttemptView,
  type ChargeView,
} from "../callingClient";
import { rememberActiveCall, readActiveCall } from "../consumerSession";
import { CallAdapterError, type CallClientAdapter, type CallAdapterEvent } from "./adapter";

/**
 * One consumer's browser call, from click to receipt (US-48, chunk V05).
 *
 * The mobile controller in `apps/mobile` holds the same four money rules, and
 * this one adds the three a browser makes necessary:
 *
 * **A tab is not the call.** The durable attempt lives on the server. A refresh,
 * a restored tab or a machine waking from sleep therefore **reconciles** — asks
 * the server what the attempt is doing — instead of dialling again. Redialling
 * would be a second call and a second charge for one thing the customer did
 * once, and it is the single most likely way a browser client bills twice.
 *
 * **Unload is best effort and never the spending control.** `releaseOnUnload`
 * tries to tell the server, and swallows every failure, because a page being
 * torn down may not finish a request at all. What actually stops a call whose
 * client vanished is V03's server-side cutoff, which does not depend on this
 * code running, completing, or existing.
 *
 * **A disposed session is inert.** Sign-out and account switch bump a
 * generation; callbacks already queued in the SDK land on a generation that no
 * longer matches and are dropped.
 *
 * Deliberately duplicated from the mobile controller rather than extracted into
 * a shared package: the two apps share no build today, and inventing a workspace
 * package to hold ~200 lines would be a larger and riskier change than the
 * duplication it removes. Worth revisiting when a third client appears.
 */

export type CallPhase =
  | "idle"
  | "preparing"
  | "connecting"
  | "ringing"
  | "answered"
  | "ended"
  | "failed";

export type MicrophoneResult = "granted" | "denied" | "no_device" | "unsupported";

export type CallSnapshot = {
  phase: CallPhase;
  attemptId: string | null;
  destinationE164: string | null;
  identityE164: string | null;
  currency: string | null;
  maxSeconds: number | null;
  maxChargeAmount: string | null;
  startedAt: number | null;
  /** Billing starts here, not at dial. Ringing is not billable. */
  answeredAt: number | null;
  muted: boolean;
  failureCode: string | null;
  endReason: string | null;
  charge: ChargeView | null;
};

export type BrowserCallSessionOptions = {
  userId: string;
  deviceId: string;
  currency: string;
  adapter: CallClientAdapter;
  requestMicrophone: () => Promise<MicrophoneResult>;
  now?: () => number;
  onChange?: (snapshot: CallSnapshot) => void;
};

const LIVE_PHASES: readonly CallPhase[] = [
  "preparing",
  "connecting",
  "ringing",
  "answered",
];

const LIVE_SERVER_STATES = new Set(["authorized", "dialing", "ringing", "answered"]);

/**
 * Turn a failure into something the person can act on.
 *
 * Unrecognised codes pass through rather than collapsing into "something went
 * wrong", so a new server-side refusal shows up in support tickets as itself.
 */
export function failureCodeFor(error: unknown): string {
  if (error instanceof CallAdapterError) {
    return error.code;
  }
  if (error instanceof CallingApiError) {
    if (error.status === 401) return "session_expired";
    if (error.code === "network_error") return "offline";
    if (error.code === "not_a_member" || error.status === 403) return "not_permitted";
    return error.code;
  }
  return "call_failed";
}

export function newIdempotencyKey(): string {
  const random = Math.random().toString(36).slice(2, 12);
  return `web-${Date.now().toString(36)}-${random}`;
}

export class BrowserCallSession {
  private readonly options: BrowserCallSessionOptions;
  private readonly now: () => number;
  private generation = 0;
  private disposed = false;
  private unsubscribe: (() => void) | null = null;
  private inFlight: Promise<void> | null = null;
  private pending: { destination: string; idempotencyKey: string } | null = null;
  private state: CallSnapshot;

  constructor(options: BrowserCallSessionOptions) {
    this.options = options;
    this.now = options.now ?? (() => Date.now());
    this.state = idleSnapshot();
    this.unsubscribe = options.adapter.subscribe((event) => {
      this.handleAdapterEvent(this.generation, event);
    });
  }

  snapshot(): CallSnapshot {
    return this.state;
  }

  /**
   * Ask the server what the remembered attempt is doing.
   *
   * Called on mount, and that covers refresh, a restored tab, a second tab and
   * a machine waking from sleep — all of which look identical from here and all
   * of which must converge on the attempt that exists rather than start a new
   * one. The server re-checks ownership of the attempt id before answering, so
   * a stale id belonging to somebody else yields nothing.
   */
  async reconcile(): Promise<void> {
    if (this.disposed) {
      return;
    }
    const attemptId = readActiveCall(this.options.userId);
    if (!attemptId) {
      return;
    }
    const generation = this.generation;
    try {
      const attempt = await getCall(attemptId);
      if (this.stale(generation)) return;
      this.adoptServerState(attempt);
    } catch (error) {
      if (this.stale(generation)) return;
      // A call we cannot ask about is a call we must not claim is running.
      rememberActiveCall(this.options.userId, null);
      this.update({ phase: "idle", failureCode: failureCodeFor(error) });
    }
  }

  async place(destination: string): Promise<void> {
    if (this.disposed) {
      return;
    }
    if (this.inFlight) {
      await this.inFlight;
      return;
    }
    if (LIVE_PHASES.includes(this.state.phase)) {
      return;
    }
    if (!this.options.adapter.available) {
      // Before the microphone prompt and before any hold. Asking for a
      // permission this build cannot use teaches people to decline it.
      this.fail("calling_unavailable");
      return;
    }
    this.pending = {
      destination,
      idempotencyKey: this.pending?.idempotencyKey ?? newIdempotencyKey(),
    };
    this.inFlight = this.run(this.generation, this.pending);
    try {
      await this.inFlight;
    } finally {
      this.inFlight = null;
    }
  }

  /** The lost-response path: the same key, so the server returns the same hold. */
  async retry(): Promise<void> {
    if (this.disposed || !this.pending) {
      return;
    }
    await this.place(this.pending.destination);
  }

  async hangup(reason = "stopped"): Promise<void> {
    const attemptId = this.state.attemptId;
    try {
      await this.options.adapter.hangup();
    } catch {
      // An adapter that cannot hang up is exactly when the server must be told.
    }
    if (attemptId) {
      await this.stopOnServer(attemptId, reason);
    }
    rememberActiveCall(this.options.userId, null);
  }

  /**
   * Best effort, on the way out. Never awaited by anything that matters.
   *
   * The browser may kill this page mid-request and nothing here can prevent
   * that. V03's cutoff is what actually bounds the spend; this only shortens
   * the window in the common case where the tab closes politely.
   */
  async releaseOnUnload(): Promise<void> {
    const attemptId = this.state.attemptId;
    if (!attemptId) {
      return;
    }
    try {
      await stopCall(attemptId, "tab_closed");
    } catch {
      // Swallowed deliberately. See the method note.
    }
  }

  async setMuted(muted: boolean): Promise<boolean> {
    if (!this.options.adapter.capabilities.mute) {
      return false;
    }
    await this.options.adapter.setMuted(muted);
    this.update({ muted });
    return true;
  }

  /** `false` rather than a throw, so the keypad can disable itself honestly. */
  async sendDigit(digit: string): Promise<boolean> {
    if (!this.options.adapter.capabilities.dtmf) {
      return false;
    }
    if (this.state.phase !== "answered") {
      return false;
    }
    await this.options.adapter.sendDigit(digit);
    return true;
  }

  dispose(): void {
    this.disposed = true;
    this.generation += 1;
    this.pending = null;
    this.state = idleSnapshot();
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.options.adapter.disconnect().catch(() => undefined);
  }

  // --- internals ---------------------------------------------------------

  private async run(
    generation: number,
    pending: { destination: string; idempotencyKey: string },
  ): Promise<void> {
    this.update({
      phase: "preparing",
      failureCode: null,
      endReason: null,
      charge: null,
      destinationE164: pending.destination,
      currency: this.options.currency,
    });

    const permission = await this.options.requestMicrophone();
    if (this.stale(generation)) return;
    if (permission !== "granted") {
      // Before authorize. A declined prompt must not leave money held.
      this.fail(
        permission === "no_device"
          ? "no_microphone"
          : permission === "unsupported"
            ? "browser_unsupported"
            : "microphone_denied",
      );
      return;
    }

    let attempt: AttemptView;
    try {
      attempt = await authorizeCall({
        destination: pending.destination,
        idempotencyKey: pending.idempotencyKey,
        currency: this.options.currency,
        deviceId: this.options.deviceId,
      });
    } catch (error) {
      if (this.stale(generation)) return;
      this.fail(failureCodeFor(error));
      return;
    }
    if (this.stale(generation)) return;

    // The hold is real from here, so every exit tells the server — and the
    // attempt is remembered so a refresh reconciles rather than redials.
    rememberActiveCall(this.options.userId, attempt.attempt_id);
    this.update({
      attemptId: attempt.attempt_id,
      identityE164: attempt.identity_e164,
      maxSeconds: attempt.max_seconds,
      maxChargeAmount: attempt.max_charge_amount,
      currency: attempt.currency,
      startedAt: this.now(),
      phase: "connecting",
    });

    try {
      const provider = await issueClientSession(this.options.deviceId, "browser");
      if (this.stale(generation)) return;
      await this.options.adapter.connect({
        token: provider.token,
        sipIdentity: provider.sip_identity,
        expiresAt: provider.expires_at,
      });
      const instruction = await startCall(attempt.attempt_id, this.options.deviceId);
      if (this.stale(generation)) return;
      await this.options.adapter.dial({
        attemptId: instruction.attempt_id,
        destinationE164: instruction.destination_e164,
        correlation: instruction.correlation,
        maxSeconds: instruction.max_seconds,
      });
    } catch (error) {
      if (this.stale(generation)) return;
      const code = failureCodeFor(error);
      await this.stopOnServer(attempt.attempt_id, code);
      rememberActiveCall(this.options.userId, null);
      if (this.stale(generation)) return;
      this.fail(code);
    }
  }

  private adoptServerState(attempt: AttemptView): void {
    const live = LIVE_SERVER_STATES.has(attempt.state);
    if (!live) {
      rememberActiveCall(this.options.userId, null);
    }
    this.update({
      attemptId: live ? attempt.attempt_id : null,
      destinationE164: attempt.destination_e164,
      identityE164: attempt.identity_e164,
      currency: attempt.currency,
      maxSeconds: attempt.max_seconds,
      maxChargeAmount: attempt.max_charge_amount,
      answeredAt: attempt.answered_at ? Date.parse(attempt.answered_at) : null,
      endReason: attempt.end_reason,
      charge: attempt.charge,
      phase: live ? phaseForState(attempt.state) : "ended",
    });
  }

  private async stopOnServer(attemptId: string, reason: string): Promise<void> {
    try {
      const attempt = await stopCall(attemptId, reason.slice(0, 100));
      if (this.state.attemptId === attemptId) {
        this.update({ endReason: attempt.end_reason, charge: attempt.charge });
      }
    } catch {
      // V03's cutoff and expiry still release the hold. This is courtesy.
    }
  }

  private handleAdapterEvent(generation: number, event: CallAdapterEvent): void {
    if (this.stale(generation)) {
      return;
    }
    switch (event.kind) {
      case "connecting":
        this.update({ phase: "connecting" });
        return;
      case "ringing":
        this.update({ phase: "ringing" });
        return;
      case "answered":
        this.update({ phase: "answered", answeredAt: this.now() });
        return;
      case "ended":
        rememberActiveCall(this.options.userId, null);
        this.update({ phase: "ended", endReason: event.reason });
        return;
      case "failed":
        rememberActiveCall(this.options.userId, null);
        this.fail(event.reason);
        return;
    }
  }

  private fail(code: string): void {
    this.update({ phase: "failed", failureCode: code });
  }

  private stale(generation: number): boolean {
    return this.disposed || generation !== this.generation;
  }

  private update(patch: Partial<CallSnapshot>): void {
    this.state = { ...this.state, ...patch };
    this.options.onChange?.(this.state);
  }
}

function phaseForState(state: string): CallPhase {
  switch (state) {
    case "answered":
      return "answered";
    case "ringing":
      return "ringing";
    case "dialing":
      return "connecting";
    default:
      return "connecting";
  }
}

function idleSnapshot(): CallSnapshot {
  return {
    phase: "idle",
    attemptId: null,
    destinationE164: null,
    identityE164: null,
    currency: null,
    maxSeconds: null,
    maxChargeAmount: null,
    startedAt: null,
    answeredAt: null,
    muted: false,
    failureCode: null,
    endReason: null,
    charge: null,
  };
}
