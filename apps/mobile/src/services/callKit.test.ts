import { Platform } from 'react-native';
import RNCallKeep from 'react-native-callkeep';
import VoipPushNotification from 'react-native-voip-push-notification';
import { createCallKitVoiceGateway, initializeCallKit } from './callKit';
import { loginTelnyxClientForIncomingCalls } from './voiceGateway';
import type { VoiceCallSession, VoiceCallState } from './voiceGateway';

jest.mock('./voiceGateway', () => ({
  ...jest.requireActual('./voiceGateway'),
  loginTelnyxClientForIncomingCalls: jest.fn(),
}));

const mockLoginForIncoming = loginTelnyxClientForIncomingCalls as jest.MockedFunction<
  typeof loginTelnyxClientForIncomingCalls
>;
const mockAddEventListener = RNCallKeep.addEventListener as jest.Mock;
const mockVoipAddEventListener = VoipPushNotification.addEventListener as jest.Mock;
const mockVoipRemoveEventListener = VoipPushNotification.removeEventListener as jest.Mock;

const originalOs = Platform.OS;

afterEach(() => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: originalOs });
  jest.clearAllMocks();
});

function setPlatform(os: 'ios' | 'android'): void {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: os });
}

function fakeSession(
  overrides: Partial<VoiceCallSession> = {},
): { session: VoiceCallSession; stateListeners: Array<(s: VoiceCallState) => void> } {
  const stateListeners: Array<(s: VoiceCallState) => void> = [];
  const session: VoiceCallSession = {
    callType: 'app_to_app',
    displayNumber: '08012345678',
    subscribeState: jest.fn((listener) => {
      stateListeners.push(listener);
      return () => undefined;
    }),
    subscribeDuration: jest.fn(() => () => undefined),
    toggleMute: jest.fn().mockResolvedValue(true),
    toggleSpeaker: jest.fn().mockResolvedValue(true),
    hangup: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  return { session, stateListeners };
}

describe('createCallKitVoiceGateway on Android', () => {
  it('returns the base gateway completely unmodified', async () => {
    setPlatform('android');
    const { session } = fakeSession();
    const base = { startCall: jest.fn().mockResolvedValue(session) };

    const gateway = createCallKitVoiceGateway(base);
    expect(gateway).toBe(base);

    await gateway.startCall('token', '08011112222');
    expect(mockAddEventListener).not.toHaveBeenCalled();
    expect(RNCallKeep.startCall).not.toHaveBeenCalled();
  });
});

describe('createCallKitVoiceGateway on iOS', () => {
  beforeEach(() => setPlatform('ios'));

  it('registers the outbound call with the native call UI before placing it', async () => {
    const { session } = fakeSession();
    const base = { startCall: jest.fn().mockResolvedValue(session) };
    const gateway = createCallKitVoiceGateway(base);

    await gateway.startCall('token', '08011112222', 'Amina');

    expect(RNCallKeep.startCall).toHaveBeenCalledWith(
      expect.any(String),
      '08011112222',
      'Amina',
      'number',
      false,
    );
    expect(base.startCall).toHaveBeenCalledWith(
      'token',
      '08011112222',
      'Amina',
      undefined,
    );
  });

  it('reports connecting/connected to CallKit as the underlying call state changes', async () => {
    const { session, stateListeners } = fakeSession();
    const base = { startCall: jest.fn().mockResolvedValue(session) };
    const gateway = createCallKitVoiceGateway(base);

    const wrapped = await gateway.startCall('token', '08011112222');
    const observed: VoiceCallState[] = [];
    wrapped.subscribeState((state) => observed.push(state));

    stateListeners[0]('connecting');
    stateListeners[0]('connected');

    expect(RNCallKeep.reportConnectingOutgoingCallWithUUID).toHaveBeenCalledTimes(1);
    expect(RNCallKeep.reportConnectedOutgoingCallWithUUID).toHaveBeenCalledTimes(1);
    expect(observed).toEqual(['connecting', 'connected']);
  });

  it('ends the CallKit call when the underlying call ends, without double-reporting connected', async () => {
    const { session, stateListeners } = fakeSession();
    const base = { startCall: jest.fn().mockResolvedValue(session) };
    const gateway = createCallKitVoiceGateway(base);

    const wrapped = await gateway.startCall('token', '08011112222');
    wrapped.subscribeState(() => undefined);

    stateListeners[0]('connected');
    stateListeners[0]('connected');
    stateListeners[0]('ended');

    expect(RNCallKeep.reportConnectedOutgoingCallWithUUID).toHaveBeenCalledTimes(1);
    expect(RNCallKeep.endCall).toHaveBeenCalledTimes(1);
  });

  it('reports CallKit end exactly once when hangup() is called explicitly and the resulting state transition also fires (matches ActiveCallScreen\'s actual usage: it calls hangup() directly AND keeps an active subscribeState listener watching for \'ended\')', async () => {
    const { session, stateListeners } = fakeSession({
      hangup: jest.fn(async () => {
        // The real TelnyxCallSession's hangup() causes the underlying call
        // to transition to 'ended', which fires the *same* state listener
        // ActiveCallScreen is already subscribed to -- simulated here by
        // firing it synchronously as part of hangup() resolving, matching
        // how the double-invocation was actually reproduced.
        stateListeners[0]('ended');
      }),
    });
    const base = { startCall: jest.fn().mockResolvedValue(session) };
    const gateway = createCallKitVoiceGateway(base);

    const wrapped = await gateway.startCall('token', '08011112222');
    wrapped.subscribeState(() => undefined);

    await wrapped.hangup();

    expect(RNCallKeep.endCall).toHaveBeenCalledTimes(1);
  });

  it('reports a failed CallKit call and rethrows when the underlying startCall rejects', async () => {
    const base = { startCall: jest.fn().mockRejectedValue(new Error('no eligibility')) };
    const gateway = createCallKitVoiceGateway(base);

    await expect(gateway.startCall('token', '08011112222')).rejects.toThrow('no eligibility');
    expect(RNCallKeep.reportEndCallWithUUID).toHaveBeenCalledWith(expect.any(String), 1);
  });

  it('the wrapped session keeps working toggleMute/toggleSpeaker/hangup (regression guard: spreading a class instance drops its prototype methods)', async () => {
    const { session } = fakeSession();
    const base = { startCall: jest.fn().mockResolvedValue(session) };
    const gateway = createCallKitVoiceGateway(base);

    const wrapped = await gateway.startCall('token', '08011112222');
    await wrapped.toggleMute();
    await wrapped.toggleSpeaker();
    await wrapped.hangup();

    expect(session.toggleMute).toHaveBeenCalled();
    expect(session.toggleSpeaker).toHaveBeenCalled();
    expect(session.hangup).toHaveBeenCalled();
    expect(RNCallKeep.endCall).toHaveBeenCalled();
    expect(wrapped.callType).toBe('app_to_app');
    expect(wrapped.displayNumber).toBe('08012345678');
  });
});

describe('initializeCallKit on Android', () => {
  it('registers no listeners and returns a no-op cleanup', () => {
    setPlatform('android');
    const cleanup = initializeCallKit('token', { onIncomingCallReady: jest.fn() });

    expect(mockAddEventListener).not.toHaveBeenCalled();
    expect(mockVoipAddEventListener).not.toHaveBeenCalled();
    expect(() => cleanup()).not.toThrow();
  });
});

describe('initializeCallKit on iOS', () => {
  beforeEach(() => setPlatform('ios'));

  function pushHandler(): (payload: object) => void {
    const call = mockVoipAddEventListener.mock.calls.find(([type]) => type === 'notification');
    return call![1];
  }

  function callKeepHandler(type: string): () => void {
    const call = mockAddEventListener.mock.calls.find(([t]) => t === type);
    return call![1];
  }

  it('registers CallKeep and VoipPushNotification listeners', () => {
    initializeCallKit('token', { onIncomingCallReady: jest.fn() });

    expect(mockVoipAddEventListener).toHaveBeenCalledWith('register', expect.any(Function));
    expect(mockVoipAddEventListener).toHaveBeenCalledWith('notification', expect.any(Function));
    expect(mockVoipAddEventListener).toHaveBeenCalledWith('didLoadWithEvents', expect.any(Function));
    expect(mockAddEventListener).toHaveBeenCalledWith('answerCall', expect.any(Function));
    expect(mockAddEventListener).toHaveBeenCalledWith('endCall', expect.any(Function));
  });

  it('a live incoming push logs in a Telnyx client and links the CallKit UUID to it', async () => {
    const mockClient = {
      setPushNotificationCallKitUUID: jest.fn(),
      processVoIPNotification: jest.fn(),
      queueAnswerFromCallKit: jest.fn(),
      queueEndFromCallKit: jest.fn(),
    };
    mockLoginForIncoming.mockResolvedValue(mockClient as never);
    const onIncomingCallReady = jest.fn();
    initializeCallKit('token', { onIncomingCallReady });

    const payload = { uuid: 'call-uuid-1', handle: '08099998888' };
    pushHandler()(payload);
    await Promise.resolve();
    await Promise.resolve();

    expect(mockLoginForIncoming).toHaveBeenCalledWith(
      'token',
      '08099998888',
      undefined,
      onIncomingCallReady,
    );
    expect(mockClient.setPushNotificationCallKitUUID).toHaveBeenCalledWith('call-uuid-1');
    expect(mockClient.processVoIPNotification).toHaveBeenCalledWith(payload);
  });

  it('ends the CallKit call if logging in for the incoming call fails', async () => {
    mockLoginForIncoming.mockRejectedValue(new Error('offline'));
    initializeCallKit('token', { onIncomingCallReady: jest.fn() });

    pushHandler()({ uuid: 'call-uuid-2', handle: '08099998888' });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(RNCallKeep.endCall).toHaveBeenCalledWith('call-uuid-2');
  });

  it('replays a buffered incoming push from didLoadWithEvents (cold-start-from-push)', async () => {
    const mockClient = {
      setPushNotificationCallKitUUID: jest.fn(),
      processVoIPNotification: jest.fn(),
      queueAnswerFromCallKit: jest.fn(),
      queueEndFromCallKit: jest.fn(),
    };
    mockLoginForIncoming.mockResolvedValue(mockClient as never);
    initializeCallKit('token', { onIncomingCallReady: jest.fn() });

    const didLoadCall = mockVoipAddEventListener.mock.calls.find(
      ([type]) => type === 'didLoadWithEvents',
    );
    const handler = didLoadCall![1] as (events: unknown[]) => void;
    handler([
      {
        name: 'RNVoipPushRemoteNotificationReceivedEvent',
        data: { uuid: 'buffered-call', handle: '08000001111' },
      },
    ]);
    await Promise.resolve();
    await Promise.resolve();

    expect(mockLoginForIncoming).toHaveBeenCalledWith(
      'token',
      '08000001111',
      undefined,
      expect.any(Function),
    );
    expect(mockClient.setPushNotificationCallKitUUID).toHaveBeenCalledWith('buffered-call');
  });

  it('queues the CallKit answer/end actions against the pending incoming-call client', async () => {
    const mockClient = {
      setPushNotificationCallKitUUID: jest.fn(),
      processVoIPNotification: jest.fn(),
      queueAnswerFromCallKit: jest.fn(),
      queueEndFromCallKit: jest.fn(),
    };
    mockLoginForIncoming.mockResolvedValue(mockClient as never);
    initializeCallKit('token', { onIncomingCallReady: jest.fn() });

    pushHandler()({ uuid: 'call-uuid-3', handle: '08099998888' });
    await Promise.resolve();
    await Promise.resolve();

    callKeepHandler('answerCall')();
    expect(mockClient.queueAnswerFromCallKit).toHaveBeenCalled();

    callKeepHandler('endCall')();
    expect(mockClient.queueEndFromCallKit).toHaveBeenCalled();
  });

  it('cleanup unsubscribes every listener', () => {
    const answerListener = { remove: jest.fn() };
    const endListener = { remove: jest.fn() };
    mockAddEventListener.mockImplementation((type: string) =>
      type === 'answerCall' ? answerListener : endListener,
    );

    const cleanup = initializeCallKit('token', { onIncomingCallReady: jest.fn() });
    cleanup();

    expect(mockVoipRemoveEventListener).toHaveBeenCalledWith('register');
    expect(mockVoipRemoveEventListener).toHaveBeenCalledWith('notification');
    expect(mockVoipRemoveEventListener).toHaveBeenCalledWith('didLoadWithEvents');
    expect(answerListener.remove).toHaveBeenCalled();
    expect(endListener.remove).toHaveBeenCalled();
  });
});
