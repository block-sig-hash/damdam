import { Platform } from 'react-native';
import RNCallKeep from 'react-native-callkeep';
import {i18n} from '../i18n';
import VoipPushNotification from 'react-native-voip-push-notification';
import uuid from 'react-native-uuid';
import {
  loginTelnyxClientForIncomingCalls,
  telnyxVoiceGateway,
  type VoiceCallSession,
  type VoiceCallState,
  type VoiceGateway,
} from './voiceGateway';
import { loadSession } from './sessionStore';

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
  /** Fires once an incoming call -- answered via the native call UI, or
   * already answered in-app -- actually connects, so the caller (
   * AuthenticatedApp) can navigate to the Active Call screen with it. */
  onIncomingCallReady: (session: VoiceCallSession) => void;
}

let voipPushToken: string | undefined;

/** Exposed for the outbound-call path (createCallKitVoiceGateway) to keep
 * Telnyx's record of this device's push token current even when the token
 * arrived via a push-registration event rather than at call-start time.
 * iOS only -- always undefined on Android (see startCall's platform note). */
export function getVoipPushToken(): string | undefined {
  return voipPushToken;
}

/**
 * Module-level, not scoped inside initializeCallKit: Android's incoming-call
 * entry point (handleAndroidIncomingCallPayload, invoked from a Headless JS
 * Task -- see CallHeadlessTaskService.kt) can run before AuthenticatedApp
 * has ever mounted in this JS context at all (the app was fully killed and
 * the incoming call itself is what's waking it), so it cannot depend on
 * anything initializeCallKit's own closure would otherwise hold.
 */
let pendingClient: Awaited<ReturnType<typeof loginTelnyxClientForIncomingCalls>> | undefined;
let answerEndListenersRegistered = false;

/** Test-only: this module intentionally keeps state above the level of any
 * single initializeCallKit call (see the comment on pendingClient) for real
 * cross-context reasons, which also means it otherwise leaks across test
 * cases sharing this module instance. Not used by production code. */
export function __resetCallKitStateForTests(): void {
  pendingClient = undefined;
  answerEndListenersRegistered = false;
}

function registerAnswerEndListeners(): () => void {
  if (answerEndListenersRegistered) {
    return () => undefined;
  }
  answerEndListenersRegistered = true;
  const answerListener = RNCallKeep.addEventListener('answerCall', () => {
    pendingClient?.queueAnswerFromCallKit();
  });
  const endListener = RNCallKeep.addEventListener('endCall', () => {
    pendingClient?.queueEndFromCallKit();
  });
  return () => {
    answerEndListenersRegistered = false;
    answerListener.remove();
    endListener.remove();
  };
}

function handleIncomingPush(
  payload: IncomingPushPayload,
  accessToken: string,
  onIncomingCallReady: (session: VoiceCallSession) => void,
): void {
  const callUuid = payload.uuid ?? String(uuid.v4());
  const callerNumber = payload.handle ?? payload.callerName ?? i18n.t('native.unknown', {ns: 'common'});

  loginTelnyxClientForIncomingCalls(accessToken, callerNumber, voipPushToken, onIncomingCallReady)
    .then((client) => {
      pendingClient = client;
      client.setPushNotificationCallKitUUID(callUuid);
      client.processVoIPNotification(payload);
    })
    .catch(() => {
      // Best-effort: native code already reported this call to the native
      // call UI synchronously before any of this ran (iOS: AppDelegate,
      // frontend-mobile.md §8.3, Apple requires that ordering; Android:
      // CallHeadlessTaskService.kt's displayIncomingCall). If login then
      // fails, ending the call here means the user sees it briefly then
      // cleared, rather than a native call screen that never resolves.
      RNCallKeep.endCall(callUuid);
    });
}

/**
 * Wires react-native-callkeep's answerCall/endCall events to the Telnyx
 * client's own documented CallKit integration points --
 * queueAnswerFromCallKit/queueEndFromCallKit, verified directly against
 * @telnyx/react-native-voice-sdk's client.ts source -- on both platforms.
 * iOS additionally wires react-native-voip-push-notification's JS event
 * surface (frontend-mobile.md §8.3); Android's incoming-call entry point is
 * handleAndroidIncomingCallPayload below instead, invoked from a Headless JS
 * Task rather than a JS-level push listener (there is no Android
 * react-native-voip-push-notification equivalent to subscribe to -- that
 * library is iOS-PushKit-specific, confirmed by its package contents having
 * no android/ directory at all). Call once per authenticated session
 * (AuthenticatedApp); returns a cleanup function.
 */
export function initializeCallKit(accessToken: string, handlers: CallKitHandlers): () => void {
  const unregisterAnswerEnd = registerAnswerEndListeners();

  // Android: a Headless JS Task may have already logged in a client for an
  // incoming call before this ever mounted (the call itself cold-started
  // the app). Re-attaching here means the now-live UI still learns once
  // that call actually connects -- onIncomingCall adds a listener rather
  // than replacing the first (a no-op one, passed by
  // handleAndroidIncomingCallPayload), both fire.
  if (Platform.OS !== 'ios' && pendingClient) {
    pendingClient.onIncomingCall(handlers.onIncomingCallReady);
  }

  if (Platform.OS !== 'ios') {
    return unregisterAnswerEnd;
  }

  const onPush = (payload: object): void => {
    handleIncomingPush(payload as IncomingPushPayload, accessToken, handlers.onIncomingCallReady);
  };

  // react-native-voip-push-notification's addEventListener has no return
  // value -- unsubscribing goes through its static removeEventListener(type),
  // unlike react-native-callkeep's addEventListener.
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

  return () => {
    VoipPushNotification.removeEventListener('register');
    VoipPushNotification.removeEventListener('notification');
    VoipPushNotification.removeEventListener('didLoadWithEvents');
    unregisterAnswerEnd();
  };
}

/**
 * Android only. Invoked from the Headless JS Task CallHeadlessTaskService.kt
 * starts when DamDamFirebaseMessagingService detects an incoming-call-shaped
 * FCM data message -- may run with no live React tree at all (app was fully
 * killed), so it reads the persisted session directly from secure storage
 * (sessionStore.ts, built for US-23) rather than depending on an
 * AuthenticatedApp-provided accessToken prop that doesn't exist yet.
 *
 * The native call UI is reported first and unconditionally (matching the
 * "report before anything else can fail" principle the iOS PushKit path
 * uses), then login proceeds only if a session is actually available.
 */
export async function handleAndroidIncomingCallPayload(payload: IncomingPushPayload): Promise<void> {
  registerAnswerEndListeners();

  const callUuid = payload.uuid ?? String(uuid.v4());
  const callerName = payload.callerName ?? payload.handle ?? 'DamDam call';
  const callerNumber = payload.handle ?? callerName;

  RNCallKeep.displayIncomingCall(callUuid, callerNumber, callerName, 'number', false);

  const session = await loadSession();
  if (!session) {
    // No persisted DamDam session to authenticate the incoming call with --
    // the native call UI is already showing, but there is nothing more this
    // device can do without one. Ends the call rather than leaving a native
    // incoming-call screen that can never actually connect.
    RNCallKeep.endCall(callUuid);
    return;
  }

  handleIncomingPush(payload, session.accessToken, () => undefined);
  // onIncomingCallReady is deliberately a no-op here: there is no live
  // AuthenticatedApp to navigate anywhere yet in a cold-started headless
  // context. If the user answers and the full app subsequently boots,
  // AuthenticatedApp's own initializeCallKit call re-attaches its real
  // onIncomingCallReady handler to this same pendingClient (see above).
}

function reportSessionToCallKit(session: VoiceCallSession, callUuid: string): VoiceCallSession {
  let reportedConnected = false;
  // Independent review finding (originally iOS-only, applies identically on
  // Android): ActiveCallScreen's hangup button calls call.hangup() directly
  // *and* keeps an active subscribeState listener watching for 'ended' --
  // the hangup completing is exactly what drives the underlying call into
  // the 'ended' state, so both branches below would otherwise fire
  // RNCallKeep.endCall() for the same callUuid on the single most common
  // hangup path. Guarded so it fires exactly once regardless of which path
  // (explicit hangup, or observing a remote hangup/drop via the state
  // listener) reports it first.
  let reportedEnded = false;
  const reportEndedOnce = () => {
    if (!reportedEnded) {
      reportedEnded = true;
      RNCallKeep.endCall(callUuid);
    }
  };
  return {
    callType: session.callType,
    displayNumber: session.displayNumber,
    subscribeState(listener: (state: VoiceCallState) => void) {
      return session.subscribeState((state) => {
        if (state === 'connecting') {
          // iOS only (no-op on Android, per react-native-callkeep's own JS
          // wrapper) -- Android's equivalent is setCurrentCallActive below.
          RNCallKeep.reportConnectingOutgoingCallWithUUID(callUuid);
        } else if (state === 'connected' && !reportedConnected) {
          reportedConnected = true;
          RNCallKeep.reportConnectedOutgoingCallWithUUID(callUuid); // iOS only, no-op on Android
          RNCallKeep.setCurrentCallActive(callUuid); // Android only, no-op on iOS
        } else if (state === 'ended' || state === 'dropped') {
          reportEndedOnce();
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
      reportEndedOnce();
    },
  };
}

/**
 * Wraps a VoiceGateway so an outbound call also registers with the native
 * call UI -- CallKit on iOS, ConnectionService on Android via the same
 * react-native-callkeep JS API, which internally adapts each call to the
 * correct native signature per platform (verified directly against its
 * index.js: RNCallKeep.startCall/endCall/reportEndCallWithUUID all branch
 * on Platform.OS internally, so this file's call sites don't need to).
 */
export function createCallKitVoiceGateway(base: VoiceGateway = telnyxVoiceGateway): VoiceGateway {
  return {
    async startCall(accessToken, phoneNumber, contactName) {
      const callUuid = String(uuid.v4());
      const displayName = contactName ?? phoneNumber;
      RNCallKeep.startCall(callUuid, phoneNumber, displayName, 'number', false);

      let session: VoiceCallSession;
      try {
        // pushNotificationDeviceToken (iOS VoIP push token) is always
        // undefined on Android here -- Android's push channel is FCM,
        // already registered independently of this call-start path (see
        // ensureAndroidCallingReady in DialPadScreen.tsx).
        session = await base.startCall(accessToken, phoneNumber, contactName, getVoipPushToken());
      } catch (error) {
        RNCallKeep.reportEndCallWithUUID(callUuid, END_CALL_REASON_FAILED);
        throw error;
      }
      return reportSessionToCallKit(session, callUuid);
    },
  };
}

/**
 * Android only (no-op, resolves immediately on iOS). Triggers
 * react-native-callkeep's own documented phone-account permission flow --
 * a native Alert asking the user to enable DamDam as a calling account,
 * then Android's phone-accounts settings screen if accepted. This shows
 * real, user-visible native UI, so it is deliberately NOT called eagerly at
 * app/session start (unlike initializeCallKit's silent iOS setup) --
 * DialPadScreen calls this once, on first mount, matching this codebase's
 * existing contextual-permission convention (Contacts permission is
 * likewise requested only when its icon is first tapped, not at launch).
 *
 * Known, disclosed limitation: until a user opens Dial Pad at least once,
 * their phone account is not enabled, and an incoming call cannot display
 * via ConnectionService on their device at all (Android, unlike iOS, has no
 * automatic/entitlement-based path -- registerPhoneAccount requires this
 * explicit call). No screen exists yet to surface this outside Dial Pad.
 */
export async function ensureAndroidCallingReady(): Promise<void> {
  if (Platform.OS === 'ios') {
    return;
  }
  await RNCallKeep.setup({
    // Unused at runtime (guarded above, this function returns before ever
    // reaching RNCallKeep.setup on iOS) -- react-native-callkeep's own
    // IOptions type requires both keys regardless of which platform's
    // config is actually read.
    ios: { appName: 'DamDam' },
    android: {
      alertTitle: i18n.t('native.callingPermissionTitle', {ns: 'common'}),
      alertDescription: i18n.t('native.callingPermissionBody', {ns: 'common'}),
      cancelButton: i18n.t('actions.cancel', {ns: 'common'}),
      okButton: i18n.t('native.enable', {ns: 'common'}),
      additionalPermissions: [],
      foregroundService: {
        channelId: 'com.damdam.app.calls',
        channelName: i18n.t('native.callChannel', {ns: 'common'}),
        notificationTitle: i18n.t('native.callInProgress', {ns: 'common'}),
      },
    },
  });
}
