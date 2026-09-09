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

jest.mock('react-native-localize', () => ({
  findBestLanguageTag: jest.fn(() => ({languageTag: 'en', isRTL: false})),
  getLocales: jest.fn(() => [{languageCode: 'en', languageTag: 'en-US', isRTL: false}]),
  addEventListener: jest.fn(() => ({remove: jest.fn()})),
}));

// Initialize the production i18next singleton for isolated component tests.
require('./src/i18n');
