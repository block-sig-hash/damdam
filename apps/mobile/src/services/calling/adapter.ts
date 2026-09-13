/**
 * The provider boundary for internet calling on mobile (US-47, chunk V04).
 *
 * `CLAUDE.md` requires every third-party integration to sit behind an internal
 * abstraction rather than being called from a screen, and calling is the case
 * that rule was written for. A WebRTC SDK is a stateful native object with its
 * own lifecycle, its own threading and its own opinions about when a call ends;
 * letting a React component talk to one directly means the call outlives the
 * component that owns it exactly once, in production, on somebody's phone.
 *
 * ## Capabilities are advertised, not assumed
 *
 * V01 recorded the SDK's *documented* surface and could prove none of it
 * live — no Telnyx account existed, no SDK was installed and no native build
 * was made. So an adapter here states what it can actually do and the
 * controller asks before acting. A UI that renders a DTMF keypad because the
 * product manager expects one, over an adapter that cannot send digits, drops
 * the customer's input silently into a bank menu.
 *
 * ## The default adapter refuses
 *
 * `UnavailableCallAdapter` is what ships until a supported SDK is installed and
 * a native build proves it. It advertises nothing and refuses to connect with a
 * named reason. That is deliberately more useful than a stub that pretends:
 * a fake that resolves would make every screen look finished and would be the
 * "mock passing itself off as evidence" the test policy forbids.
 */

export type AudioRoute = 'earpiece' | 'speaker' | 'bluetooth';

export interface CallClientCapabilities {
  /** Can the local microphone be muted without ending the call? */
  mute: boolean;
  /** Can in-band digits be sent after answer? Bank menus need this. */
  dtmf: boolean;
  /** Can the output route be moved between earpiece, speaker and Bluetooth? */
  audioRoute: boolean;
  /**
   * Does audio survive the app going to background or the screen locking?
   * **Unproven for every adapter today.** A `false` here is a disclosure, not
   * a defect: the assignment requires lifecycle limitations to be disclosed
   * rather than discovered by a customer mid-call.
   */
  backgroundCall: boolean;
}

export const NO_CAPABILITIES: CallClientCapabilities = {
  mute: false,
  dtmf: false,
  audioRoute: false,
  backgroundCall: false,
};

/** A short-lived, per-device provider session. Never persisted to disk. */
export interface ProviderSession {
  token: string;
  sipIdentity: string;
  expiresAt: string;
}

/**
 * One attempt's dialling instruction, as the server issued it.
 *
 * `correlation` is echoed to the provider so its events can be matched back to
 * our attempt. It identifies; it does not authorize, and the server re-checks
 * ownership from the database before acting on anything it names.
 */
export interface DialInstruction {
  attemptId: string;
  destinationE164: string;
  correlation: string;
  maxSeconds: number;
}

export type CallAdapterEvent =
  | { kind: 'connecting' }
  | { kind: 'ringing' }
  | { kind: 'answered' }
  | { kind: 'ended'; reason: string }
  | { kind: 'failed'; reason: string };

export type CallAdapterListener = (event: CallAdapterEvent) => void;

export interface CallClientAdapter {
  /** Identifies the implementation in diagnostics. Never shown to a customer. */
  readonly name: string;
  /**
   * Can this build place an internet call at all?
   *
   * Separate from `capabilities`, which describe a *working* adapter's optional
   * features. `false` means there is no dialling path in this binary, and the
   * controller checks it before doing anything else — including asking for the
   * microphone. Prompting for a permission a build cannot use trains people to
   * decline it, and it is the reason chunk 08 kept `RECORD_AUDIO` out of the
   * Android manifest in the first place.
   */
  readonly available: boolean;
  readonly capabilities: CallClientCapabilities;
  connect(session: ProviderSession): Promise<void>;
  dial(instruction: DialInstruction): Promise<void>;
  hangup(): Promise<void>;
  setMuted(muted: boolean): Promise<void>;
  sendDigit(digit: string): Promise<void>;
  setAudioRoute(route: AudioRoute): Promise<void>;
  subscribe(listener: CallAdapterListener): () => void;
  /** Tear down the provider session. Called on sign-out and account switch. */
  disconnect(): Promise<void>;
}

export class CallAdapterError extends Error {
  readonly code: string;

  constructor(code: string, message?: string) {
    super(message ?? code);
    this.name = 'CallAdapterError';
    this.code = code;
  }
}

/**
 * The adapter in the production build today.
 *
 * No supported Telnyx SDK is installed in this repository and no native build
 * has exercised one, so there is nothing honest for this to do except refuse
 * and say why. `capabilities` is all-false, which makes every in-call control
 * render as unavailable rather than as a button that does nothing.
 *
 * Replacing it is the gated part of V04: it needs a Telnyx account (D1), the
 * SDK added to `package.json`, and iOS and Android builds that prove connect,
 * dial, DTMF, mute, routing and hangup on real hardware.
 */
export class UnavailableCallAdapter implements CallClientAdapter {
  readonly name = 'unavailable';
  readonly available = false;
  readonly capabilities = NO_CAPABILITIES;

  async connect(): Promise<void> {
    throw new CallAdapterError('sdk_unavailable');
  }

  async dial(): Promise<void> {
    throw new CallAdapterError('sdk_unavailable');
  }

  async hangup(): Promise<void> {
    // Deliberately silent. Hanging up is the safety path, and a controller
    // tearing a call down must never be stopped by the absence of an SDK.
  }

  async setMuted(): Promise<void> {
    throw new CallAdapterError('capability_not_available');
  }

  async sendDigit(): Promise<void> {
    throw new CallAdapterError('capability_not_available');
  }

  async setAudioRoute(): Promise<void> {
    throw new CallAdapterError('capability_not_available');
  }

  subscribe(): () => void {
    return () => undefined;
  }

  async disconnect(): Promise<void> {
    // Nothing was ever connected.
  }
}
