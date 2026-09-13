import {
  authorizeCall,
  issueClientSession,
  startCall,
  stopCall,
  type AttemptView,
  type ChargeView,
} from '../../api/callingClient';
import { ApiError } from '../../api/http';
import {
  CallAdapterError,
  type AudioRoute,
  type CallAdapterEvent,
  type CallClientAdapter,
  type CallClientCapabilities,
} from './adapter';

/**
 * One customer's outbound internet call, from tap to receipt (US-47, chunk V04).
 *
 * The controller exists because the interesting rules are not about rendering.
 * They are about money and identity, and both of them break in ways a screen
 * cannot see:
 *
 * **A hold is taken before a call can be dialled.** So the microphone is asked
 * for *first*. A customer who declines the permission prompt after authorization
 * has money reserved against a call that never happened, and gets it back only
 * when an expiry sweep runs.
 *
 * **One placement is one hold.** A double tap, a retry after a lost response
 * and a re-render all reuse the same idempotency key. The server keys on it,
 * so a second attempt returns the first attempt rather than reserving again.
 *
 * **A client that gives up must say so.** Every path that abandons an
 * authorized attempt calls `stopCall`, because the hold is already real by
 * then. The server's own cutoff still runs if this process dies — that is V03's
 * job and it does not depend on us — but leaving the server to discover it is
 * a customer staring at a balance they cannot spend.
 *
 * **A disposed session is inert.** An SDK does not know the account changed and
 * will keep delivering callbacks for the call it is still holding. Every
 * callback is checked against a generation counter, so the next user's screen
 * cannot inherit the previous user's call — nor end it.
 */

export type CallPhase =
  | 'idle'
  | 'preparing'
  | 'connecting'
  | 'ringing'
  | 'answered'
  | 'ended'
  | 'failed';

export type MicrophonePermission = 'granted' | 'denied' | 'blocked';

export interface CallSnapshot {
  phase: CallPhase;
  attemptId: string | null;
  destinationE164: string | null;
  identityE164: string | null;
  organizationId: string | null;
  currency: string | null;
  maxSeconds: number | null;
  maxChargeAmount: string | null;
  /** When dialling began. Not billable time — see `answeredAt`. */
  startedAt: number | null;
  /**
   * When the far end answered. The elapsed estimate runs from here, because
   * ringing is not billable and an app whose timer disagrees with the receipt
   * is an app the customer stops believing.
   */
  answeredAt: number | null;
  muted: boolean;
  audioRoute: AudioRoute;
  failureCode: string | null;
  endReason: string | null;
  charge: ChargeView | null;
  capabilities: CallClientCapabilities;
}

export interface PlaceRequest {
  destination: string;
  currency: string;
  organizationId?: string | null;
  requestedSeconds?: number;
}

export interface CallSessionOptions {
  accessToken: string;
  /** Whose call this is. Half of the guard against a leaked callback. */
  userId: string;
  deviceId: string;
  deviceLabel?: string | null;
  adapter: CallClientAdapter;
  requestMicrophone: () => Promise<MicrophonePermission>;
  now?: () => number;
  onChange?: (snapshot: CallSnapshot) => void;
}

const LIVE_PHASES: readonly CallPhase[] = [
  'preparing',
  'connecting',
  'ringing',
  'answered',
];

/**
 * Turn a server or adapter failure into something a customer can act on.
 *
 * The mapping is deliberately narrow. An unrecognised code is passed through
 * rather than flattened into "something went wrong", so a new server-side
 * refusal shows up in support tickets as itself instead of hiding behind a
 * generic message for a release cycle.
 */
export function failureCodeFor(error: unknown): string {
  if (error instanceof CallAdapterError) {
    return error.code;
  }
  if (error instanceof ApiError) {
    if (error.status === 401) return 'session_expired';
    if (error.code === 'network_error') return 'offline';
    if (error.code === 'not_a_member' || error.status === 403) return 'not_permitted';
    return error.code;
  }
  return 'call_failed';
}

export class CallSessionController {
  private readonly options: Required<Pick<CallSessionOptions, 'now'>> &
    CallSessionOptions;
  private readonly now: () => number;
  private generation = 0;
  private disposed = false;
  private unsubscribe: (() => void) | null = null;
  private inFlight: Promise<void> | null = null;
  /** Held across retries so a second attempt is the same attempt. */
  private pending: { request: PlaceRequest; idempotencyKey: string } | null = null;
  private state: CallSnapshot;

  constructor(options: CallSessionOptions) {
    this.options = { now: () => Date.now(), ...options };
    this.now = this.options.now;
    this.state = this.idleSnapshot();
    this.unsubscribe = options.adapter.subscribe(event => {
      this.handleAdapterEvent(this.generation, event);
    });
  }

  snapshot(): CallSnapshot {
    return this.state;
  }

  /**
   * Place a call: permission, hold, provider session, dial — in that order.
   *
   * Concurrent calls collapse onto the first. A customer tapping twice is not
   * asking for two calls, and the idempotency key would make the second a
   * no-op at the server anyway; single-flighting here means it never leaves.
   */
  async place(request: PlaceRequest): Promise<void> {
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
      // Before the permission prompt and before any hold. A build with no
      // dialling path must not ask for a microphone it cannot use.
      this.fail('calling_unavailable');
      return;
    }
    this.pending = {
      request,
      idempotencyKey: this.pending?.idempotencyKey ?? newIdempotencyKey(),
    };
    this.inFlight = this.run(this.generation, this.pending);
    try {
      await this.inFlight;
    } finally {
      this.inFlight = null;
    }
  }

  /**
   * Try the same placement again, with the same key.
   *
   * This is the lost-response path: the request may well have succeeded and
   * taken a hold. Reusing the key is what makes the retry converge on that
   * attempt instead of reserving a second time.
   */
  async retry(): Promise<void> {
    if (this.disposed || !this.pending) {
      return;
    }
    await this.place(this.pending.request);
  }

  async hangup(reason = 'stopped'): Promise<void> {
    const attemptId = this.state.attemptId;
    try {
      await this.options.adapter.hangup();
    } catch {
      // An SDK that cannot hang up is precisely when the server must be told.
      // Swallowing this and continuing is the whole point of the ordering.
    }
    if (attemptId) {
      await this.stopOnServer(attemptId, reason);
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

  /**
   * Send one in-band digit, or report that this adapter cannot.
   *
   * Returning `false` rather than throwing lets the keypad disable itself.
   * Accepting a digit an adapter will drop is worse than refusing it: the
   * customer believes they navigated a bank menu and they did not.
   */
  async sendDigit(digit: string): Promise<boolean> {
    if (!this.options.adapter.capabilities.dtmf) {
      return false;
    }
    if (this.state.phase !== 'answered') {
      return false;
    }
    await this.options.adapter.sendDigit(digit);
    return true;
  }

  async setAudioRoute(route: AudioRoute): Promise<boolean> {
    if (!this.options.adapter.capabilities.audioRoute) {
      return false;
    }
    await this.options.adapter.setAudioRoute(route);
    this.update({ audioRoute: route });
    return true;
  }

  /**
   * Retire this session. Called on sign-out, account switch and unmount.
   *
   * The generation bump is the load-bearing line: callbacks already queued
   * inside the SDK will still arrive, and after this they land on a generation
   * that no longer matches and are dropped.
   */
  dispose(): void {
    this.disposed = true;
    this.generation += 1;
    this.pending = null;
    this.state = this.idleSnapshot();
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.options.adapter.disconnect().catch(() => undefined);
  }

  // --- internals ---------------------------------------------------------

  private async run(
    generation: number,
    pending: { request: PlaceRequest; idempotencyKey: string },
  ): Promise<void> {
    const { request, idempotencyKey } = pending;
    this.update({
      phase: 'preparing',
      failureCode: null,
      endReason: null,
      charge: null,
      destinationE164: request.destination,
      organizationId: request.organizationId ?? null,
      currency: request.currency,
    });

    const permission = await this.options.requestMicrophone();
    if (this.stale(generation)) return;
    if (permission !== 'granted') {
      // Before authorize, deliberately. See the class note.
      this.fail(permission === 'blocked' ? 'microphone_blocked' : 'microphone_denied');
      return;
    }

    let attempt: AttemptView;
    try {
      attempt = await authorizeCall({
        accessToken: this.options.accessToken,
        destination: request.destination,
        idempotencyKey,
        currency: request.currency,
        organizationId: request.organizationId ?? null,
        deviceId: this.options.deviceId,
        requestedSeconds: request.requestedSeconds,
      });
    } catch (error) {
      if (this.stale(generation)) return;
      this.fail(failureCodeFor(error));
      return;
    }
    if (this.stale(generation)) return;

    // From here the hold is real, and every exit has to tell the server.
    this.update({
      attemptId: attempt.attempt_id,
      identityE164: attempt.identity_e164,
      maxSeconds: attempt.max_seconds,
      maxChargeAmount: attempt.max_charge_amount,
      currency: attempt.currency,
      startedAt: this.now(),
      phase: 'connecting',
    });

    try {
      const session = await issueClientSession({
        accessToken: this.options.accessToken,
        deviceId: this.options.deviceId,
        deviceLabel: this.options.deviceLabel ?? null,
      });
      if (this.stale(generation)) return;
      await this.options.adapter.connect({
        token: session.token,
        sipIdentity: session.sip_identity,
        expiresAt: session.expires_at,
      });
      const instruction = await startCall({
        accessToken: this.options.accessToken,
        attemptId: attempt.attempt_id,
        deviceId: this.options.deviceId,
      });
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
      if (this.stale(generation)) return;
      this.fail(code);
    }
  }

  private async stopOnServer(attemptId: string, reason: string): Promise<void> {
    try {
      const attempt = await stopCall({
        accessToken: this.options.accessToken,
        attemptId,
        reason: reason.slice(0, 100),
      });
      if (this.state.attemptId === attemptId) {
        this.update({ endReason: attempt.end_reason, charge: attempt.charge });
      }
    } catch {
      // The server's own cutoff and expiry still release the hold (V03). This
      // is the courteous path, not the guarantee, and failing it must not stop
      // the local teardown that follows.
    }
  }

  private handleAdapterEvent(generation: number, event: CallAdapterEvent): void {
    if (this.stale(generation)) {
      return;
    }
    switch (event.kind) {
      case 'connecting':
        this.update({ phase: 'connecting' });
        return;
      case 'ringing':
        this.update({ phase: 'ringing' });
        return;
      case 'answered':
        this.update({ phase: 'answered', answeredAt: this.now() });
        return;
      case 'ended':
        this.update({ phase: 'ended', endReason: event.reason });
        return;
      case 'failed':
        this.fail(event.reason);
        return;
    }
  }

  private fail(code: string): void {
    this.update({ phase: 'failed', failureCode: code });
  }

  private stale(generation: number): boolean {
    return this.disposed || generation !== this.generation;
  }

  private update(patch: Partial<CallSnapshot>): void {
    this.state = { ...this.state, ...patch };
    this.options.onChange?.(this.state);
  }

  private idleSnapshot(): CallSnapshot {
    return {
      phase: 'idle',
      attemptId: null,
      destinationE164: null,
      identityE164: null,
      organizationId: null,
      currency: null,
      maxSeconds: null,
      maxChargeAmount: null,
      startedAt: null,
      answeredAt: null,
      muted: false,
      audioRoute: 'earpiece',
      failureCode: null,
      endReason: null,
      charge: null,
      capabilities: this.options.adapter.capabilities,
    };
  }
}

/**
 * A key for one placement.
 *
 * The server requires at least eight characters and scopes the key to the
 * caller, so this only has to be unique per user per attempt. `Math.random` is
 * adequate for that and `crypto.randomUUID` is not available on every supported
 * React Native runtime without a polyfill.
 */
export function newIdempotencyKey(): string {
  const random = Math.random().toString(36).slice(2, 12);
  return `call-${Date.now().toString(36)}-${random}`;
}
