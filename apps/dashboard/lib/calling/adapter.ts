/**
 * The browser provider boundary for outbound calling (US-48, chunk V05).
 *
 * Same rule as everywhere else in this repo: a third-party SDK is reached
 * through an internal abstraction, never from a component. In a browser the
 * reason is sharper than usual — a WebRTC client owns a `RTCPeerConnection`, a
 * media stream and a websocket, all of which outlive React's idea of a
 * component, and all of which keep costing money after the element that created
 * them has been unmounted.
 *
 * ## What the browser can be asked, and what it cannot
 *
 * Unlike the mobile side, two of these questions are answerable today without
 * any SDK: whether the browser supports capture at all, and whether the person
 * will grant the microphone. `mediaSupport()` and the permission request in
 * `session.ts` are therefore real implementations rather than placeholders.
 *
 * What is *not* answerable is everything after that — connect, dial, DTMF,
 * mute, hangup — because no supported SDK is installed. `UnavailableCallAdapter`
 * says so by refusing, rather than resolving and letting every screen look
 * finished.
 */

export type CallClientCapabilities = {
  mute: boolean;
  dtmf: boolean;
  /** Whether the output device can be chosen. Chrome-only in practice. */
  audioOutput: boolean;
};

export const NO_CAPABILITIES: CallClientCapabilities = {
  mute: false,
  dtmf: false,
  audioOutput: false,
};

export type ProviderSession = {
  token: string;
  sipIdentity: string;
  expiresAt: string;
};

export type DialInstruction = {
  attemptId: string;
  destinationE164: string;
  correlation: string;
  maxSeconds: number;
};

export type CallAdapterEvent =
  | { kind: "connecting" }
  | { kind: "ringing" }
  | { kind: "answered" }
  | { kind: "ended"; reason: string }
  | { kind: "failed"; reason: string };

export type CallAdapterListener = (event: CallAdapterEvent) => void;

export interface CallClientAdapter {
  readonly name: string;
  /** Can this build place a call at all? Checked before any prompt. */
  readonly available: boolean;
  readonly capabilities: CallClientCapabilities;
  connect(session: ProviderSession): Promise<void>;
  dial(instruction: DialInstruction): Promise<void>;
  hangup(): Promise<void>;
  setMuted(muted: boolean): Promise<void>;
  sendDigit(digit: string): Promise<void>;
  subscribe(listener: CallAdapterListener): () => void;
  disconnect(): Promise<void>;
}

export class CallAdapterError extends Error {
  readonly code: string;

  constructor(code: string, message?: string) {
    super(message ?? code);
    this.name = "CallAdapterError";
    this.code = code;
  }
}

export type MediaSupport = "supported" | "unsupported" | "insecure_context";

/**
 * Can this browser capture audio at all?
 *
 * `getUserMedia` is only exposed on a secure context, so a page served over
 * plain HTTP has no microphone regardless of what the person clicks. That is a
 * different problem from an old browser and gets its own answer, because the
 * fix is a URL rather than a different machine.
 */
export function mediaSupport(): MediaSupport {
  if (typeof window === "undefined") {
    return "unsupported";
  }
  if (window.isSecureContext === false) {
    return "insecure_context";
  }
  return typeof navigator !== "undefined" &&
    typeof navigator.mediaDevices?.getUserMedia === "function"
    ? "supported"
    : "unsupported";
}

/**
 * The adapter this build ships. It refuses, and names why.
 *
 * No supported Telnyx WebRTC SDK is installed: D1 is open, there is no account,
 * and V01 could verify the browser client only from documentation. Replacing
 * this is a change to `registry.ts` plus one new adapter module — the boundary
 * exists so that it is.
 */
export class UnavailableCallAdapter implements CallClientAdapter {
  readonly name = "unavailable";
  readonly available = false;
  readonly capabilities = NO_CAPABILITIES;

  async connect(): Promise<void> {
    throw new CallAdapterError("sdk_unavailable");
  }

  async dial(): Promise<void> {
    throw new CallAdapterError("sdk_unavailable");
  }

  async hangup(): Promise<void> {
    // Silent on purpose. Tearing a call down must never fail for want of an SDK.
  }

  async setMuted(): Promise<void> {
    throw new CallAdapterError("capability_not_available");
  }

  async sendDigit(): Promise<void> {
    throw new CallAdapterError("capability_not_available");
  }

  subscribe(): () => void {
    return () => undefined;
  }

  async disconnect(): Promise<void> {
    // Nothing was connected.
  }
}
