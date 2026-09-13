import {
  CallAdapterError,
  type AudioRoute,
  type CallAdapterEvent,
  type CallAdapterListener,
  type CallClientAdapter,
  type CallClientCapabilities,
  type DialInstruction,
  type ProviderSession,
} from './adapter';

/**
 * A controllable adapter for tests and the component gallery.
 *
 * It exists so the *controller's* rules — one hold per placement, a server stop
 * after every failed dial, a disposed session that ignores late callbacks — can
 * be tested without an SDK. It proves nothing about Telnyx, and nothing that
 * uses it may be offered as evidence that internet calling works: V01's
 * capability matrix is the record of what is documented, and live proof is
 * still outstanding on D1.
 */
export class FakeCallAdapter implements CallClientAdapter {
  readonly name = 'fake';
  readonly available = true;
  readonly capabilities: CallClientCapabilities;

  muted = false;
  route: AudioRoute = 'earpiece';
  digits: string[] = [];
  session: ProviderSession | null = null;
  dialled: DialInstruction | null = null;
  hangups = 0;

  private listeners: CallAdapterListener[] = [];
  private dialFailure: string | null = null;
  private hangupFails = false;

  constructor(capabilities: Partial<CallClientCapabilities> = {}) {
    this.capabilities = {
      mute: true,
      dtmf: true,
      audioRoute: true,
      backgroundCall: false,
      ...capabilities,
    };
  }

  failNextDial(code: string): void {
    this.dialFailure = code;
  }

  failNextHangup(): void {
    this.hangupFails = true;
  }

  emit(event: CallAdapterEvent): void {
    for (const listener of [...this.listeners]) {
      listener(event);
    }
  }

  async connect(session: ProviderSession): Promise<void> {
    this.session = session;
  }

  async dial(instruction: DialInstruction): Promise<void> {
    if (this.dialFailure) {
      const code = this.dialFailure;
      this.dialFailure = null;
      throw new CallAdapterError(code);
    }
    this.dialled = instruction;
    this.emit({ kind: 'connecting' });
  }

  async hangup(): Promise<void> {
    this.hangups += 1;
    if (this.hangupFails) {
      this.hangupFails = false;
      throw new CallAdapterError('hangup_failed');
    }
  }

  async setMuted(muted: boolean): Promise<void> {
    this.muted = muted;
  }

  async sendDigit(digit: string): Promise<void> {
    this.digits.push(digit);
  }

  async setAudioRoute(route: AudioRoute): Promise<void> {
    this.route = route;
  }

  subscribe(listener: CallAdapterListener): () => void {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(entry => entry !== listener);
    };
  }

  async disconnect(): Promise<void> {
    this.session = null;
    this.listeners = [];
  }
}
