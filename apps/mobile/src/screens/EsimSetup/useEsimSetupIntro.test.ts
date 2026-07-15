import { act, renderHook, waitFor } from '@testing-library/react-native';
import { Linking } from 'react-native';
import { logDeviceCompatibility } from '../../api/esimClient';
import { checkEsimCompatibility } from '../../utils/esimCompatibility';
import { hasSeenEsimWarning, markEsimWarningSeen } from '../../utils/esimWarningSeen';
import { useEsimSetupIntro } from './useEsimSetupIntro';

jest.mock('../../api/esimClient', () => ({
  logDeviceCompatibility: jest.fn(),
}));
jest.mock('../../utils/esimCompatibility', () => ({
  checkEsimCompatibility: jest.fn(),
}));
jest.mock('../../utils/esimWarningSeen', () => ({
  hasSeenEsimWarning: jest.fn(),
  markEsimWarningSeen: jest.fn(),
}));

const mockCheck = checkEsimCompatibility as jest.MockedFunction<typeof checkEsimCompatibility>;
const mockLog = logDeviceCompatibility as jest.MockedFunction<typeof logDeviceCompatibility>;
const mockHasSeen = hasSeenEsimWarning as jest.MockedFunction<typeof hasSeenEsimWarning>;
const mockMarkSeen = markEsimWarningSeen as jest.MockedFunction<typeof markEsimWarningSeen>;

beforeEach(() => {
  mockCheck.mockReset();
  mockLog.mockReset().mockResolvedValue(undefined);
  mockHasSeen.mockReset().mockResolvedValue(false);
  mockMarkSeen.mockReset().mockResolvedValue(undefined);
  jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
});

describe('useEsimSetupIntro', () => {
  it('AC-10.1/10.2: compatible device logs immediately and reaches the compatible stage', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone 15',
      osVersion: '18.1',
      supported: true,
    });

    const { result } = await renderHook(() =>
      useEsimSetupIntro({ accessToken: 'token', packageId: 'package-1' }),
    );

    await waitFor(() => expect(result.current.stage).toBe('compatible'));
    expect(mockLog).toHaveBeenCalledWith('token', {
      platform: 'ios',
      device_model: 'iPhone 15',
      os_version: '18.1',
      esim_supported: true,
    });
    expect(mockHasSeen).not.toHaveBeenCalled();
  });

  it('AC-10.3: incompatible + not yet seen reaches the warning stage without logging yet', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone X',
      osVersion: '16.0',
      supported: false,
    });
    mockHasSeen.mockResolvedValue(false);

    const { result } = await renderHook(() =>
      useEsimSetupIntro({ accessToken: 'token', packageId: 'package-1' }),
    );

    await waitFor(() => expect(result.current.stage).toBe('warning'));
    expect(mockLog).not.toHaveBeenCalled();
  });

  it('AC-10.6: incompatible + already seen skips the modal and goes straight to qr-only', async () => {
    mockCheck.mockResolvedValue({
      platform: 'android',
      deviceModel: 'Tecno Spark 10',
      osVersion: '13',
      supported: false,
    });
    mockHasSeen.mockResolvedValue(true);

    const { result } = await renderHook(() =>
      useEsimSetupIntro({ accessToken: 'token', packageId: 'package-1' }),
    );

    await waitFor(() => expect(result.current.stage).toBe('qr-only'));
    expect(mockLog).not.toHaveBeenCalled();
  });

  it('AC-10.4: Continue marks the warning seen, logs, and proceeds to qr-only', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone X',
      osVersion: '16.0',
      supported: false,
    });
    mockHasSeen.mockResolvedValue(false);

    const { result } = await renderHook(() =>
      useEsimSetupIntro({ accessToken: 'token', packageId: 'package-1' }),
    );
    await waitFor(() => expect(result.current.stage).toBe('warning'));

    await act(async () => {
      await result.current.handleWarningContinue();
    });

    expect(mockMarkSeen).toHaveBeenCalledTimes(1);
    expect(mockLog).toHaveBeenCalledWith('token', {
      platform: 'ios',
      device_model: 'iPhone X',
      os_version: '16.0',
      esim_supported: false,
    });
    expect(result.current.stage).toBe('qr-only');
  });

  it('AC-10.5: Support opens WhatsApp with the order reference and proceeds the same as Continue', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone X',
      osVersion: '16.0',
      supported: false,
    });
    mockHasSeen.mockResolvedValue(false);

    const { result } = await renderHook(() =>
      useEsimSetupIntro({ accessToken: 'token', packageId: 'package-42' }),
    );
    await waitFor(() => expect(result.current.stage).toBe('warning'));

    await act(async () => {
      await result.current.handleWarningSupport();
    });

    expect(Linking.openURL).toHaveBeenCalledWith(
      expect.stringMatching(/^https:\/\/wa\.me\/\d+\?text=.*package-42/),
    );
    expect(mockMarkSeen).toHaveBeenCalledTimes(1);
    expect(result.current.stage).toBe('qr-only');
  });
});
