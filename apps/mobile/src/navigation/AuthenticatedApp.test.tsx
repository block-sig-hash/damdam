import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { getEsim } from '../api/esimClient';
import { getPackageStatus } from '../api/paymentClient';
import {
  optIntoArrivalGeofence,
  registerPushInstallation,
  subscribeToActivationDeepLinks,
} from '../services/arrivalPrompts';
import { AuthenticatedApp } from './AuthenticatedApp';

jest.mock('react-native-device-info', () => ({
  __esModule: true,
  default: { getModel: () => 'Test phone' },
}));
jest.mock('../api/esimClient', () => ({ getEsim: jest.fn() }));
jest.mock('../api/paymentClient', () => ({ getPackageStatus: jest.fn() }));
jest.mock('../services/arrivalPrompts', () => ({
  ...jest.requireActual('../services/arrivalPrompts'),
  optIntoArrivalGeofence: jest.fn(),
  registerPushInstallation: jest.fn(),
  subscribeToActivationDeepLinks: jest.fn(),
}));
jest.mock('../screens/EsimActivation/EsimActivationFlow', () => {
  const { Text } = require('react-native');
  return {
    EsimActivationFlow: () => <Text testID="wired-activation-flow">Activation flow</Text>,
  };
});
jest.mock('../screens/EsimSetup/EsimQrCodeScreen', () => {
  const { Text } = require('react-native');
  return { EsimQrCodeScreen: () => <Text>QR fallback</Text> };
});
jest.mock('../screens/DialPad/DialPadScreen', () => {
  const { Pressable, Text } = require('react-native');
  return {
    DialPadScreen: ({
      onCallStarted,
      pstnMinutesRemaining,
    }: {
      onCallStarted: (call: object) => void;
      pstnMinutesRemaining: number;
    }) => (
      <>
        <Text>Dial balance {pstnMinutesRemaining}</Text>
        <Pressable
          testID="mock-start-pstn"
          onPress={() =>
            onCallStarted({
              callType: 'pstn',
              displayNumber: '08099999999',
              subscribeState: () => jest.fn(),
              subscribeDuration: () => jest.fn(),
              toggleMute: jest.fn(),
              toggleSpeaker: jest.fn(),
              hangup: jest.fn(),
            })
          }
        >
          <Text>Start PSTN</Text>
        </Pressable>
      </>
    ),
  };
});
jest.mock('../screens/ActiveCall/ActiveCallScreen', () => {
  const { Pressable, Text } = require('react-native');
  return {
    ActiveCallScreen: ({ onFinished }: { onFinished: () => void }) => (
      <Pressable testID="mock-finish-call" onPress={onFinished}>
        <Text>Finish call</Text>
      </Pressable>
    ),
  };
});

const mockGetEsim = getEsim as jest.MockedFunction<typeof getEsim>;
const mockGetPackageStatus = getPackageStatus as jest.MockedFunction<typeof getPackageStatus>;
const mockRegisterPush = registerPushInstallation as jest.MockedFunction<
  typeof registerPushInstallation
>;
const mockSubscribe = subscribeToActivationDeepLinks as jest.MockedFunction<
  typeof subscribeToActivationDeepLinks
>;
const mockGeofence = optIntoArrivalGeofence as jest.MockedFunction<
  typeof optIntoArrivalGeofence
>;

beforeEach(() => {
  jest.clearAllMocks();
  mockGetEsim.mockResolvedValue({
    esim_profile_id: 'profile-1',
    iccid: '8901000000000000001',
    qr_code_url: 'https://example.test/qr.png',
    status: 'downloaded',
  });
  mockGetPackageStatus.mockResolvedValue({
    status: 'active',
    data_gb_remaining: 4.25,
    pstn_minutes_remaining: 30,
  });
  mockRegisterPush.mockResolvedValue('registered');
  mockGeofence.mockResolvedValue('registered');
  mockSubscribe.mockReturnValue(jest.fn());
});

it('wires authenticated bootstrap, date banner, and activation navigation', async () => {
  await render(
    <AuthenticatedApp
      accessToken="access-token"
      departureDate="2026-07-20"
      packageId="package-1"
    />,
  );

  await waitFor(() => {
    expect(mockRegisterPush).toHaveBeenCalledWith('access-token');
    expect(mockGeofence).toHaveBeenCalledWith('package-1');
    expect(mockGetEsim).toHaveBeenCalledWith('access-token', 'package-1');
  });
  expect(screen.getByTestId('esim-activation-banner')).toBeTruthy();
  await act(async () => fireEvent.press(screen.getByTestId('esim-banner-activate')));
  expect(screen.getByTestId('wired-activation-flow')).toBeTruthy();
});

it('deep-links an authenticated pilgrim directly into activation', async () => {
  let openPackage: ((packageId: string) => void) | undefined;
  mockSubscribe.mockImplementation((handler) => {
    openPackage = handler;
    return jest.fn();
  });
  await render(
    <AuthenticatedApp accessToken="access-token" departureDate={null} />,
  );

  await act(async () => openPackage?.('linked-package'));
  expect(screen.getByTestId('wired-activation-flow')).toBeTruthy();
  expect(mockGeofence).toHaveBeenCalledWith('linked-package');
});

it('AC-14.7: refreshes the displayed PSTN balance after a completed call', async () => {
  await render(
    <AuthenticatedApp
      accessToken="access-token"
      departureDate={null}
      packageId="package-1"
    />,
  );
  await waitFor(() => expect(mockGetPackageStatus).toHaveBeenCalledTimes(1));
  await fireEvent.press(screen.getByTestId('open-call-tab'));
  expect(screen.getByText('Dial balance 30')).toBeTruthy();
  await fireEvent.press(screen.getByTestId('mock-start-pstn'));
  mockGetPackageStatus.mockResolvedValue({
    status: 'active',
    data_gb_remaining: 4.25,
    pstn_minutes_remaining: 29.5,
  });
  await fireEvent.press(screen.getByTestId('mock-finish-call'));
  await waitFor(() => expect(screen.getByText('Dial balance 29.5')).toBeTruthy());
});
