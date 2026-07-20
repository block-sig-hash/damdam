/* global jest */
// React 19 requires test renderers to opt into act() diagnostics explicitly.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const mockConnectedNetworkState = {
  type: 'wifi',
  isConnected: true,
  isInternetReachable: true,
  details: null,
};

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  NetInfoStateType: {unknown: 'unknown', wifi: 'wifi'},
  default: {
    addEventListener: jest.fn(() => jest.fn()),
    fetch: jest.fn().mockResolvedValue(mockConnectedNetworkState),
  },
}));

jest.mock('react-native-background-fetch', () => ({
  __esModule: true,
  default: {
    NETWORK_TYPE_ANY: 1,
    configure: jest.fn().mockResolvedValue(2),
    scheduleTask: jest.fn().mockResolvedValue(true),
    finish: jest.fn(),
    stop: jest.fn().mockResolvedValue(undefined),
  },
}));

jest.mock('@react-native-community/geolocation', () => ({
  __esModule: true,
  default: {
    requestAuthorization: jest.fn(success => success()),
    getCurrentPosition: jest.fn((success, error) => error({code: 2})),
  },
}));

// Both react-native-callkeep and react-native-voip-push-notification build a
// NativeEventEmitter around NativeModules.RNCallKeep/RNVoipPushNotificationManager
// at import time -- neither exists in the Jest environment (no real native
// module registered), and NativeEventEmitter throws on a null/undefined
// argument. Mocking the whole package (rather than trying to populate
// NativeModules) avoids ever constructing the real emitter in tests.
jest.mock('react-native-callkeep', () => ({
  __esModule: true,
  default: {
    setup: jest.fn().mockResolvedValue(true),
    addEventListener: jest.fn(() => ({remove: jest.fn()})),
    removeEventListener: jest.fn(),
    displayIncomingCall: jest.fn(),
    startCall: jest.fn(),
    endCall: jest.fn(),
    reportEndCallWithUUID: jest.fn(),
    reportConnectingOutgoingCallWithUUID: jest.fn(),
    reportConnectedOutgoingCallWithUUID: jest.fn(),
    setMutedCall: jest.fn(),
    CONSTANTS: {END_CALL_REASONS: {FAILED: 1, REMOTE_ENDED: 2, UNANSWERED: 3}},
  },
}));

jest.mock('react-native-voip-push-notification', () => ({
  __esModule: true,
  default: {
    RNVoipPushRemoteNotificationsRegisteredEvent: 'RNVoipPushRemoteNotificationsRegisteredEvent',
    RNVoipPushRemoteNotificationReceivedEvent: 'RNVoipPushRemoteNotificationReceivedEvent',
    RNVoipPushDidLoadWithEvents: 'RNVoipPushDidLoadWithEvents',
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    registerVoipToken: jest.fn(),
    onVoipNotificationCompleted: jest.fn(),
  },
}));
