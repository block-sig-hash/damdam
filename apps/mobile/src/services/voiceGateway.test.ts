import { getVoiceToken } from '../api/voiceClient';
import { loginTelnyxClientForIncomingCalls, telnyxVoiceGateway } from './voiceGateway';

jest.mock('../api/voiceClient', () => ({
  getVoiceToken: jest.fn(),
}));

const mockCreateTelnyxVoipClient = jest.fn();
const mockCreateTokenConfig = jest.fn((token: string, _options: Record<string, unknown>) => ({
  token,
}));

jest.mock(
  '@telnyx/react-voice-commons-sdk',
  () => ({
    createTelnyxVoipClient: (...args: unknown[]) => mockCreateTelnyxVoipClient(...args),
    createTokenConfig: (...args: [string, Record<string, unknown>]) =>
      mockCreateTokenConfig(...args),
    VoicePnBridge: { toggleSpeaker: jest.fn().mockResolvedValue(true) },
  }),
  { virtual: true },
);

const mockGetVoiceToken = getVoiceToken as jest.MockedFunction<typeof getVoiceToken>;

function fakeTelnyxCall(overrides: Record<string, unknown> = {}) {
  return {
    currentState: 'NEW',
    currentDuration: 0,
    callState$: { subscribe: jest.fn(() => ({ unsubscribe: jest.fn() })) },
    duration$: { subscribe: jest.fn(() => ({ unsubscribe: jest.fn() })) },
    toggleMute: jest.fn().mockResolvedValue(undefined),
    hangup: jest.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

beforeEach(() => {
  mockGetVoiceToken.mockReset();
  mockCreateTelnyxVoipClient.mockReset();
  mockCreateTokenConfig.mockClear();
});

describe('telnyxVoiceGateway.startCall', () => {
  it('places an outbound call with the fetched credential and no push token when none is given', async () => {
    mockGetVoiceToken.mockResolvedValue({
      token: 'sip-token',
      sip_username: 'user1',
      expires_at: '2026-01-01T00:00:00Z',
      call_type: 'app_to_app',
      destination: 'sip:user2@telnyx',
    });
    const call = fakeTelnyxCall();
    const newCall = jest.fn().mockResolvedValue(call);
    const loginWithToken = jest.fn().mockResolvedValue(undefined);
    mockCreateTelnyxVoipClient.mockReturnValue({ loginWithToken, newCall });

    const session = await telnyxVoiceGateway.startCall('access-token', '08011112222', 'Amina');

    expect(mockGetVoiceToken).toHaveBeenCalledWith('access-token', '08011112222');
    expect(mockCreateTelnyxVoipClient).toHaveBeenCalledWith(
      expect.not.objectContaining({ pushNotificationDeviceToken: expect.anything() }),
    );
    expect(newCall).toHaveBeenCalledWith('sip:user2@telnyx', 'Amina');
    expect(session.callType).toBe('app_to_app');
  });

  it('threads a push notification device token through to the client when provided', async () => {
    mockGetVoiceToken.mockResolvedValue({
      token: 'sip-token',
      sip_username: 'user1',
      expires_at: '2026-01-01T00:00:00Z',
      call_type: 'pstn',
      destination: '+2348012345678',
    });
    const call = fakeTelnyxCall();
    mockCreateTelnyxVoipClient.mockReturnValue({
      loginWithToken: jest.fn().mockResolvedValue(undefined),
      newCall: jest.fn().mockResolvedValue(call),
    });

    await telnyxVoiceGateway.startCall(
      'access-token',
      '08011112222',
      undefined,
      'voip-push-token-abc',
    );

    expect(mockCreateTelnyxVoipClient).toHaveBeenCalledWith(
      expect.objectContaining({ pushNotificationDeviceToken: 'voip-push-token-abc' }),
    );
  });
});

describe('loginTelnyxClientForIncomingCalls', () => {
  it('logs in and wires telnyx.call.incoming to construct a VoiceCallSession', async () => {
    mockGetVoiceToken.mockResolvedValue({
      token: 'sip-token',
      sip_username: 'user1',
      expires_at: '2026-01-01T00:00:00Z',
      call_type: 'pstn',
      destination: 'unused-for-incoming',
    });
    const call = fakeTelnyxCall({ currentState: 'ACTIVE' });
    let incomingHandler: ((call: unknown) => void) | undefined;
    const loginWithToken = jest.fn().mockResolvedValue(undefined);
    mockCreateTelnyxVoipClient.mockReturnValue({
      loginWithToken,
      newCall: jest.fn(),
      on: jest.fn((event: string, handler: (call: unknown) => void) => {
        if (event === 'telnyx.call.incoming') incomingHandler = handler;
      }),
      setPushNotificationCallKitUUID: jest.fn(),
      processVoIPNotification: jest.fn(),
      queueAnswerFromCallKit: jest.fn(),
      queueEndFromCallKit: jest.fn(),
    });

    const onIncomingCall = jest.fn();
    const client = await loginTelnyxClientForIncomingCalls(
      'access-token',
      '08099998888',
      'push-token',
      onIncomingCall,
    );

    expect(mockGetVoiceToken).toHaveBeenCalledWith('access-token', '08099998888');
    expect(loginWithToken).toHaveBeenCalled();
    expect(incomingHandler).toBeDefined();

    incomingHandler!(call);
    expect(onIncomingCall).toHaveBeenCalledTimes(1);
    const session = onIncomingCall.mock.calls[0][0] as { callType: string; displayNumber: string };
    expect(session.callType).toBe('pstn');
    expect(session.displayNumber).toBe('08099998888');
    expect(typeof client.queueAnswerFromCallKit).toBe('function');
  });
});
