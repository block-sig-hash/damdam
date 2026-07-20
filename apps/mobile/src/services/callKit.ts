import { Platform } from 'react-native';
import RNCallKeep from 'react-native-callkeep';
import VoipPushNotification from 'react-native-voip-push-notification';
import uuid from 'react-native-uuid';
import {
  loginTelnyxClientForIncomingCalls,
  telnyxVoiceGateway,
  type VoiceCallSession,
  type VoiceCallState,
  type VoiceGateway,
} from './voiceGateway';

/** RNCallKeep.CONSTANTS.END_CALL_REASONS.FAILED, inlined rather than
 * imported to avoid pulling in the native module at module-eval time in
 * environments (e.g. this file's own unit tests) that mock it partially. */
const END_CALL_REASON_FAILED = 1;

interface IncomingPushPayload {
  uuid?: string;
  handle?: string;
  callerName?: string;
  [key: string]: unknown;
}

interface DelayedEvent {
  name: string;
  data: unknown;
}

export interface CallKitHandlers {
  /** Fires once an incoming call -- answered via the native CallKit UI, or
   * already answered in-app -- actually connects, so the caller (
   * AuthenticatedApp) can navigate to the Active Call screen with it. */
  onIncomingCallReady: (session: VoiceCallSession) => void;
}

let voipPushToken: string | undefined;

/** Exposed for the outbound-call path (createCallKitVoiceGateway) to keep
 * Telnyx's record of this device's push token current even when the token
 * arrived via a push-registration event rather than at call-start time. */
export function getVoipPushToken(): string | undefined {
  return voipPushToken;
}

function handleIncomingPush(
  payload: IncomingPushPayload,
  accessToken: string,
  onIncomingCallReady: (session: VoiceCallSession) => void,
  setPendingClient: (client: Awaited<ReturnType<typeof loginTelnyxClientForIncomingCalls>>) => void,
): void {
  const callUuid = payload.uuid ?? String(uuid.v4());
  const callerNumber = payload.handle ?? payload.callerName ?? 'Unknown';

  loginTelnyxClientForIncomingCalls(accessToken, callerNumber, voipPushToken, onIncomingCallReady)
    .then((client) => {
      setPendingClient(client);
      client.setPushNotificationCallKitUUID(callUuid);
      client.processVoIPNotification(payload);
    })
    .catch(() => {
      // Best-effort: native code already reported this call to CallKit
      // synchronously before any of this ran (frontend-mobile.md §8.3 --
      // Apple requires that ordering). If login then fails, ending the
      // call here means the user sees it briefly then cleared, rather
      // than a native call screen that never resolves at all.
      RNCallKeep.endCall(callUuid);
    });
}

/**
 * iOS only (frontend-mobile.md §8.3). Wires react-native-callkeep and
 * react-native-voip-push-notification's JS event surface to the Telnyx
 * client's own documented CallKit integration points --
 * setPushNotificationCallKitUUID/processVoIPNotification/
 * queueAnswerFromCallKit/queueEndFromCallKit, verified directly against
 * @telnyx/react-native-voice-sdk's client.ts source, not guessed from
 * README prose. Call once per authenticated session (AuthenticatedApp);
 * returns a cleanup function.
 */
export function initializeCallKit(accessToken: string, handlers: CallKitHandlers): () => void {
  if (Platform.OS !== 'ios') {
    return () => undefined;
  }

  let pendingClient: Awaited<ReturnType<typeof loginTelnyxClientForIncomingCalls>> | undefined;

  const onPush = (payload: object): void => {
    handleIncomingPush(
      payload as IncomingPushPayload,
      accessToken,
      handlers.onIncomingCallReady,
      (client) => {
        pendingClient = client;
      },
    );
  };

  // react-native-voip-push-notification's addEventListener has no return
  // value -- unsubscribing goes through its static removeEventListener(type),
  // unlike react-native-callkeep's addEventListener below.
  VoipPushNotification.addEventListener('register', (token: string) => {
    voipPushToken = token;
  });
  VoipPushNotification.addEventListener('notification', onPush);
  VoipPushNotification.addEventListener('didLoadWithEvents', (events: DelayedEvent[]) => {
    // Replays whatever the native side buffered before JS finished
    // loading -- the cold-start-from-push case: the app was killed, a
    // VoIP push woke it, AppDelegate reported the call to CallKit
    // natively, and only now has JS caught up enough to subscribe.
    for (const event of events ?? []) {
      if (event.name === VoipPushNotification.RNVoipPushRemoteNotificationReceivedEvent) {
        onPush(event.data as IncomingPushPayload);
      } else if (event.name === VoipPushNotification.RNVoipPushRemoteNotificationsRegisteredEvent) {
        voipPushToken = event.data as string;
      }
    }
  });

  const answerListener = RNCallKeep.addEventListener('answerCall', () => {
    pendingClient?.queueAnswerFromCallKit();
  });
  const endListener = RNCallKeep.addEventListener('endCall', () => {
    pendingClient?.queueEndFromCallKit();
  });

  return () => {
    VoipPushNotification.removeEventListener('register');
    VoipPushNotification.removeEventListener('notification');
    VoipPushNotification.removeEventListener('didLoadWithEvents');
    answerListener.remove();
    endListener.remove();
  };
}

function reportSessionToCallKit(session: VoiceCallSession, callUuid: string): VoiceCallSession {
  let reportedConnected = false;
  return {
    callType: session.callType,
    displayNumber: session.displayNumber,
    subscribeState(listener: (state: VoiceCallState) => void) {
      return session.subscribeState((state) => {
        if (state === 'connecting') {
          RNCallKeep.reportConnectingOutgoingCallWithUUID(callUuid);
        } else if (state === 'connected' && !reportedConnected) {
          reportedConnected = true;
          RNCallKeep.reportConnectedOutgoingCallWithUUID(callUuid);
        } else if (state === 'ended' || state === 'dropped') {
          RNCallKeep.endCall(callUuid);
        }
        listener(state);
      });
    },
    subscribeDuration(listener: (seconds: number) => void) {
      return session.subscribeDuration(listener);
    },
    toggleMute() {
      return session.toggleMute();
    },
    toggleSpeaker() {
      return session.toggleSpeaker();
    },
    async hangup() {
      await session.hangup();
      RNCallKeep.endCall(callUuid);
    },
  };
}

/**
 * Wraps a VoiceGateway so an outbound call also registers with the native
 * call UI (CallKit) -- iOS only. On Android this returns `base` completely
 * unmodified, so Android's existing in-app-only call behavior is
 * unaffected by this module even being imported.
 */
export function createCallKitVoiceGateway(base: VoiceGateway = telnyxVoiceGateway): VoiceGateway {
  if (Platform.OS !== 'ios') {
    return base;
  }
  return {
    async startCall(accessToken, phoneNumber, contactName) {
      const callUuid = String(uuid.v4());
      const displayName = contactName ?? phoneNumber;
      RNCallKeep.startCall(callUuid, phoneNumber, displayName, 'number', false);

      let session: VoiceCallSession;
      try {
        session = await base.startCall(accessToken, phoneNumber, contactName, getVoipPushToken());
      } catch (error) {
        RNCallKeep.reportEndCallWithUUID(callUuid, END_CALL_REASON_FAILED);
        throw error;
      }
      return reportSessionToCallKit(session, callUuid);
    },
  };
}
