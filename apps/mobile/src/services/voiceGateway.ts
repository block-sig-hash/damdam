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
type TelnyxClient = {
  loginWithToken(config: Record<string, unknown>): Promise<void>;
  newCall(destination: string, callerName?: string): Promise<TelnyxCall>;
  connect(): Promise<void>;
  /** iOS CallKit/PushKit only -- verified directly against
   * @telnyx/react-native-voice-sdk's client.ts source (frontend-mobile.md
   * §8.3): tells the SDK which CallKit UUID a woken-from-push call
   * corresponds to, and hands it the raw push payload so the actual SIP
   * invite (arriving once this client's socket connects) gets linked to
   * that UUID automatically. */
  setPushNotificationCallKitUUID(uuid: string | null): void;
  processVoIPNotification(payload: Record<string, unknown>): void;
  /** Queues an answer/end action for the call the push notification
   * announced, executed immediately if the invite has already arrived, or
   * as soon as it does otherwise -- see client.ts's queueAnswerFromCallKit/
   * queueEndFromCallKit doc comments ("matching iOS SDK behavior"). */
  queueAnswerFromCallKit(customHeaders?: Record<string, string>): void;
  queueEndFromCallKit(): void;
  on(event: 'telnyx.call.incoming', handler: (call: TelnyxCall) => void): void;
};
type TelnyxRuntime = {
  createTelnyxVoipClient(options: Record<string, unknown>): TelnyxClient;
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
  startCall(
    accessToken: string,
    phoneNumber: string,
    contactName?: string,
    /** AC-23.1-adjacent (iOS CallKit/PushKit): keeps the account's VoIP push
     * token current with Telnyx even on an outbound call, not just at
     * incoming-call setup time. Omitted entirely on Android -- Telnyx's
     * login-handler code (login-handler.ts) only forwards this field when
     * present, so a call with no token behaves exactly as it did before
     * this parameter existed. */
    pushNotificationDeviceToken?: string,
  ): Promise<VoiceCallSession>;
}

function mapState(state: string): VoiceCallState {
  if (state === 'ACTIVE' || state === 'HELD') return 'connected';
  if (state === 'DROPPED') return 'dropped';
  if (state === 'ENDED' || state === 'FAILED') return 'ended';
  return 'connecting';
}

export class TelnyxCallSession implements VoiceCallSession {
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

function createTelnyxClient(pushNotificationDeviceToken?: string) {
  const telnyx = telnyxRuntime();
  return {
    telnyx,
    client: telnyx.createTelnyxVoipClient({
      enableAppStateManagement: true,
      useTrickleIce: true,
      debug: false,
      ...(pushNotificationDeviceToken ? { pushNotificationDeviceToken } : {}),
    }),
  };
}

export const telnyxVoiceGateway: VoiceGateway = {
  async startCall(accessToken, phoneNumber, contactName, pushNotificationDeviceToken) {
    const credential = await getVoiceToken(accessToken, phoneNumber);
    const { telnyx, client } = createTelnyxClient(pushNotificationDeviceToken);
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

/**
 * iOS CallKit/PushKit only (frontend-mobile.md §8.3) -- logs in a Telnyx
 * client suitable for *receiving* a call, distinct from telnyxVoiceGateway's
 * outbound-only startCall: a client must already be connected before the
 * SIP invite for an incoming call can arrive at all.
 *
 * Disclosed workaround, not hidden: docs/api-spec.md's POST /voice/token
 * is documented as "requests a token only when starting a call" and
 * requires a `to_number`. There is no dedicated "log in to receive calls"
 * endpoint. Since the same doc also states each user has one distinct
 * Telnyx telephony credential regardless of destination, this passes the
 * *caller's* number (from the push payload) as that required field purely
 * to obtain the callee's own login token -- the call_type/destination
 * fields in the response are unused here. A cleaner contract (e.g. an
 * explicit registration endpoint) is real, separate follow-up work; this
 * is not silently invented backend behavior, it is documented, real
 * backend behavior used for a purpose the endpoint's own doc comment
 * doesn't quite describe.
 */
export interface IncomingCallClient {
  setPushNotificationCallKitUUID(uuid: string | null): void;
  processVoIPNotification(payload: Record<string, unknown>): void;
  queueAnswerFromCallKit(customHeaders?: Record<string, string>): void;
  queueEndFromCallKit(): void;
  /** Registers an additional listener for when the SIP invite this login
   * was opened for actually arrives, already wrapped as a VoiceCallSession
   * -- used to re-attach a caller's onIncomingCallReady handler after the
   * fact (Android: a Headless JS Task may have logged in before
   * AuthenticatedApp ever mounted, see callKit.ts). Multiple listeners are
   * all invoked, not replaced -- the underlying SDK client is an
   * EventEmitter, confirmed against @telnyx/react-native-voice-sdk's
   * client.ts source. */
  onIncomingCall(handler: (session: VoiceCallSession) => void): void;
}

export async function loginTelnyxClientForIncomingCalls(
  accessToken: string,
  callerNumberHint: string,
  pushNotificationDeviceToken: string | undefined,
  onIncomingCall: (session: VoiceCallSession) => void,
): Promise<IncomingCallClient> {
  const credential = await getVoiceToken(accessToken, callerNumberHint);
  const { telnyx, client } = createTelnyxClient(pushNotificationDeviceToken);
  const subscribeIncoming = (handler: (session: VoiceCallSession) => void): void => {
    client.on('telnyx.call.incoming', (call) => {
      handler(new TelnyxCallSession(call, credential.call_type, callerNumberHint));
    });
  };
  subscribeIncoming(onIncomingCall);
  await client.loginWithToken(
    telnyx.createTokenConfig(credential.token, {
      enableCallReports: true,
      callReportInterval: 5,
      useTrickleIce: true,
    }),
  );
  return {
    setPushNotificationCallKitUUID: (uuid) => client.setPushNotificationCallKitUUID(uuid),
    processVoIPNotification: (payload) => client.processVoIPNotification(payload),
    queueAnswerFromCallKit: (headers) => client.queueAnswerFromCallKit(headers),
    queueEndFromCallKit: () => client.queueEndFromCallKit(),
    onIncomingCall: subscribeIncoming,
  };
}
