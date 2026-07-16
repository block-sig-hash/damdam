import { getVoiceToken, type CallType } from '../api/voiceClient';

// The official bridge's lower-level `@telnyx/react-native-voice-sdk` 1.0.0
// dependency publishes `lib/index.ts` as both its runtime and type entrypoint.
// RN 0.86 then type-checks Telnyx's source using DamDam's stricter options and
// reports upstream errors. Keep the official runtime while defining only the
// stable public surface used here; this can become a normal typed import when
// that lower-level package publishes declarations.
type Subscription = { unsubscribe(): void };
type Observable<T> = { subscribe(listener: (value: T) => void): Subscription };
type TelnyxCall = {
  currentState: string;
  currentDuration: number;
  callState$: Observable<string>;
  duration$: Observable<number>;
  toggleMute(): Promise<void>;
  hangup(): Promise<void>;
};
type TelnyxRuntime = {
  createTelnyxVoipClient(options: Record<string, unknown>): {
    loginWithToken(config: Record<string, unknown>): Promise<void>;
    newCall(destination: string, callerName?: string): Promise<TelnyxCall>;
  };
  createTokenConfig(token: string, options: Record<string, unknown>): Record<string, unknown>;
  VoicePnBridge: { toggleSpeaker(): Promise<boolean> };
};

function telnyxRuntime(): TelnyxRuntime {
  return require('@telnyx/react-voice-commons-sdk') as TelnyxRuntime;
}

export type VoiceCallState = 'connecting' | 'connected' | 'ended' | 'dropped';

export interface VoiceCallSession {
  callType: CallType;
  displayNumber: string;
  subscribeState(listener: (state: VoiceCallState) => void): () => void;
  subscribeDuration(listener: (seconds: number) => void): () => void;
  toggleMute(): Promise<boolean>;
  toggleSpeaker(): Promise<boolean>;
  hangup(): Promise<void>;
}

export interface VoiceGateway {
  startCall(accessToken: string, phoneNumber: string, contactName?: string): Promise<VoiceCallSession>;
}

function mapState(state: string): VoiceCallState {
  if (state === 'ACTIVE' || state === 'HELD') return 'connected';
  if (state === 'DROPPED') return 'dropped';
  if (state === 'ENDED' || state === 'FAILED') return 'ended';
  return 'connecting';
}

class TelnyxCallSession implements VoiceCallSession {
  private muted = false;

  constructor(
    private readonly call: TelnyxCall,
    readonly callType: CallType,
    readonly displayNumber: string,
  ) {}

  subscribeState(listener: (state: VoiceCallState) => void): () => void {
    listener(mapState(this.call.currentState));
    const subscription = this.call.callState$.subscribe((state) => listener(mapState(state)));
    return () => subscription.unsubscribe();
  }

  subscribeDuration(listener: (seconds: number) => void): () => void {
    listener(this.call.currentDuration);
    const subscription = this.call.duration$.subscribe(listener);
    return () => subscription.unsubscribe();
  }

  async toggleMute(): Promise<boolean> {
    await this.call.toggleMute();
    this.muted = !this.muted;
    return this.muted;
  }

  toggleSpeaker(): Promise<boolean> {
    return telnyxRuntime().VoicePnBridge.toggleSpeaker();
  }

  hangup(): Promise<void> {
    return this.call.hangup();
  }
}

export const telnyxVoiceGateway: VoiceGateway = {
  async startCall(accessToken, phoneNumber, contactName) {
    const credential = await getVoiceToken(accessToken, phoneNumber);
    const telnyx = telnyxRuntime();
    const client = telnyx.createTelnyxVoipClient({
      enableAppStateManagement: true,
      useTrickleIce: true,
      debug: false,
    });
    await client.loginWithToken(
      telnyx.createTokenConfig(credential.token, {
        enableCallReports: true,
        callReportInterval: 5,
        useTrickleIce: true,
      }),
    );
    const call = await client.newCall(credential.destination, contactName);
    return new TelnyxCallSession(call, credential.call_type, phoneNumber);
  },
};
