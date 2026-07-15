import { NativeModules, Platform } from 'react-native';
import DeviceInfo from 'react-native-device-info';
import { checkEsimCompatibility } from './esimCompatibility';

jest.mock('react-native-device-info', () => ({
  getModel: jest.fn(),
  getSystemVersion: jest.fn(),
  getDeviceId: jest.fn(),
}));

const mockGetModel = DeviceInfo.getModel as jest.MockedFunction<typeof DeviceInfo.getModel>;
const mockGetSystemVersion = DeviceInfo.getSystemVersion as jest.MockedFunction<
  typeof DeviceInfo.getSystemVersion
>;
const mockGetDeviceId = DeviceInfo.getDeviceId as jest.MockedFunction<
  typeof DeviceInfo.getDeviceId
>;

beforeEach(() => {
  mockGetModel.mockReset().mockReturnValue('Test Device');
  mockGetSystemVersion.mockReset().mockReturnValue('16.0');
  mockGetDeviceId.mockReset().mockReturnValue('');
  delete (NativeModules as Record<string, unknown>).EsimCompatibility;
});

describe('checkEsimCompatibility — iOS (AC-10.1, device-model allowlist)', () => {
  beforeEach(() => {
    Platform.OS = 'ios';
  });

  it('reports supported for iPhone XS (iPhone11,2), the oldest eSIM-capable generation', async () => {
    mockGetDeviceId.mockReturnValue('iPhone11,2');

    const result = await checkEsimCompatibility();

    expect(result).toEqual({
      platform: 'ios',
      deviceModel: 'Test Device',
      osVersion: '16.0',
      supported: true,
    });
  });

  it('reports unsupported for a pre-XS iPhone (iPhone10,x — iPhone 8/X generation)', async () => {
    mockGetDeviceId.mockReturnValue('iPhone10,6');

    const result = await checkEsimCompatibility();

    expect(result.supported).toBe(false);
  });

  it('reports supported for a later generation (iPhone15,4 — iPhone 15)', async () => {
    mockGetDeviceId.mockReturnValue('iPhone15,4');

    expect((await checkEsimCompatibility()).supported).toBe(true);
  });

  it('reports unsupported for an unrecognized device-id format (e.g. simulator)', async () => {
    mockGetDeviceId.mockReturnValue('x86_64');

    expect((await checkEsimCompatibility()).supported).toBe(false);
  });
});

describe('checkEsimCompatibility — Android (AC-10.1, EuiccManager bridge)', () => {
  beforeEach(() => {
    Platform.OS = 'android';
  });

  it('reports supported when the native module resolves true', async () => {
    (NativeModules as Record<string, unknown>).EsimCompatibility = {
      hasEuicc: jest.fn().mockResolvedValue(true),
    };

    const result = await checkEsimCompatibility();

    expect(result).toEqual({
      platform: 'android',
      deviceModel: 'Test Device',
      osVersion: '16.0',
      supported: true,
    });
  });

  it('reports unsupported when the native module resolves false', async () => {
    (NativeModules as Record<string, unknown>).EsimCompatibility = {
      hasEuicc: jest.fn().mockResolvedValue(false),
    };

    expect((await checkEsimCompatibility()).supported).toBe(false);
  });

  it('reports unsupported (not a crash) when the native module rejects', async () => {
    (NativeModules as Record<string, unknown>).EsimCompatibility = {
      hasEuicc: jest.fn().mockRejectedValue(new Error('bridge unavailable')),
    };

    expect((await checkEsimCompatibility()).supported).toBe(false);
  });

  it('reports unsupported (not a crash) when the native module is missing entirely', async () => {
    expect((await checkEsimCompatibility()).supported).toBe(false);
  });
});
