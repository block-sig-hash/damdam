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

// Both of these build native bridges at import time and throw under Jest
// (`new NativeEventEmitter()` with a null module). Mocked here rather than in
// each suite because they are reached transitively — chunk 19's purchase flow
// pulls in the eSIM capability check, which pulls in both — and a suite should
// not have to know that to render a tab. Tests that care about the values
// override these with their own factory.
jest.mock('react-native-device-info', () => ({
  __esModule: true,
  default: {
    getModel: () => 'Test phone',
    getSystemVersion: () => '16.0',
    getDeviceId: () => 'iPhone14,2',
  },
}));

jest.mock('react-native-sim-cards-manager', () => ({
  __esModule: true,
  default: {isEsimSupported: () => Promise.resolve(true)},
}));

jest.mock('react-native-localize', () => ({
  findBestLanguageTag: jest.fn(() => ({languageTag: 'en', isRTL: false})),
  getLocales: jest.fn(() => [{languageCode: 'en', languageTag: 'en-US', isRTL: false}]),
  addEventListener: jest.fn(() => ({remove: jest.fn()})),
}));

// Initialize the production i18next singleton for isolated component tests.
require('./src/i18n');
