import { qualityFromNetwork } from './useNetworkQuality';

jest.mock('@react-native-community/netinfo', () => ({
  __esModule: true,
  default: { addEventListener: jest.fn(() => jest.fn()) },
}));

it('AC-14.5/6: maps cellular generation and offline state to visible call quality', () => {
  expect(
    qualityFromNetwork({
      type: 'cellular',
      isConnected: true,
      isInternetReachable: true,
      details: { cellularGeneration: '4g' },
    } as never),
  ).toBe('good');
  expect(
    qualityFromNetwork({
      type: 'cellular',
      isConnected: false,
      isInternetReachable: false,
      details: { cellularGeneration: null },
    } as never),
  ).toBe('poor');
});
