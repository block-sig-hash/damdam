import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { logDeviceCompatibility } from '../../api/esimClient';
import { checkEsimCompatibility } from '../../utils/esimCompatibility';
import { hasSeenEsimWarning } from '../../utils/esimWarningSeen';
import { EsimSetupIntroScreen } from './EsimSetupIntroScreen';

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

beforeEach(() => {
  mockCheck.mockReset();
  mockLog.mockReset().mockResolvedValue(undefined);
  mockHasSeen.mockReset().mockResolvedValue(false);
});

describe('EsimSetupIntroScreen', () => {
  it('AC-10.2: shows the compatible CTA and hands off on tap', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone 15',
      osVersion: '18.1',
      supported: true,
    });
    const onProceed = jest.fn();

    await render(
      <EsimSetupIntroScreen accessToken="token" packageId="package-1" onProceed={onProceed} />,
    );

    expect(await screen.findByTestId('esim-setup-download')).toBeTruthy();
    await act(async () => {
      fireEvent.press(screen.getByTestId('esim-setup-download'));
    });
    expect(onProceed).toHaveBeenCalledWith('package-1');
  });

  it('AC-10.3: shows the warning modal automatically for an incompatible, unseen device', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone X',
      osVersion: '16.0',
      supported: false,
    });

    await render(
      <EsimSetupIntroScreen accessToken="token" packageId="package-1" onProceed={jest.fn()} />,
    );

    expect(await screen.findByTestId('device-compatibility-warning-modal')).toBeTruthy();
    expect(screen.getByText(/does not appear to support eSIM/)).toBeTruthy();
  });

  it('AC-10.4: tapping Continue on the modal dismisses it and shows the QR-only CTA', async () => {
    mockCheck.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone X',
      osVersion: '16.0',
      supported: false,
    });
    const onProceed = jest.fn();

    await render(
      <EsimSetupIntroScreen accessToken="token" packageId="package-1" onProceed={onProceed} />,
    );
    await screen.findByTestId('esim-warning-continue');

    await act(async () => {
      fireEvent.press(screen.getByTestId('esim-warning-continue'));
    });

    await waitFor(() => expect(screen.getByTestId('esim-setup-view-qr')).toBeTruthy());
    await act(async () => {
      fireEvent.press(screen.getByTestId('esim-setup-view-qr'));
    });
    expect(onProceed).toHaveBeenCalledWith('package-1');
  });
});
