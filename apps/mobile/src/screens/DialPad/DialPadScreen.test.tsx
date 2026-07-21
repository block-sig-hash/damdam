import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { getCallHistory, getVoiceEligibility } from '../../api/voiceClient';
import { useNetworkQuality } from '../../hooks/useNetworkQuality';
import { DialPadScreen } from './DialPadScreen';

jest.mock('../../api/voiceClient', () => ({
  getCallHistory: jest.fn(),
  getVoiceEligibility: jest.fn(),
}));
jest.mock('../../hooks/useNetworkQuality', () => ({ useNetworkQuality: jest.fn() }));
jest.mock('../../services/voiceGateway', () => ({ telnyxVoiceGateway: { startCall: jest.fn() } }));

const eligibility = getVoiceEligibility as jest.MockedFunction<typeof getVoiceEligibility>;
const history = getCallHistory as jest.MockedFunction<typeof getCallHistory>;
const network = useNetworkQuality as jest.MockedFunction<typeof useNetworkQuality>;

beforeEach(() => {
  jest.clearAllMocks();
  network.mockReturnValue({ connected: true, quality: 'good' });
  history.mockResolvedValue([]);
  eligibility.mockResolvedValue({
    allowed: true,
    call_type: 'app_to_app',
    destination: 'gencred1',
    reason: null,
    pstn_minutes_remaining: 0,
  });
});

afterEach(async () => cleanup());

async function enterNumber(): Promise<void> {
  for (const digit of '08098765432') {
    await fireEvent.press(screen.getByTestId(`dial-key-${digit}`));
  }
  await waitFor(() => expect(eligibility).toHaveBeenCalled());
}

it('allows the screenshot harness to replace native calling setup', async () => {
  const callingReadiness = jest.fn().mockResolvedValue(undefined);
  await render(
    <DialPadScreen
      accessToken="access"
      pstnMinutesRemaining={10}
      onCallStarted={jest.fn()}
      callingReadiness={callingReadiness}
    />,
  );

  await waitFor(() => expect(callingReadiness).toHaveBeenCalledTimes(1));
});

it('allows the screenshot harness to replace the simulator network snapshot', async () => {
  network.mockReturnValue({ connected: false, quality: 'poor' });
  await render(
    <DialPadScreen
      accessToken="access"
      pstnMinutesRemaining={10}
      onCallStarted={jest.fn()}
      networkQualityOverride={{ connected: true, quality: 'excellent' }}
    />,
  );

  expect(screen.queryByText('Calling requires an internet connection')).toBeNull();
});

it('AC-14.2/8: zero-minute users can pick a contact and place a free app-to-app call', async () => {
  const call = { callType: 'app_to_app', displayNumber: '08098765432' } as never;
  const gateway = { startCall: jest.fn().mockResolvedValue(call) };
  const onStarted = jest.fn();
  await render(
    <DialPadScreen
      accessToken="access"
      pstnMinutesRemaining={0}
      onCallStarted={onStarted}
      voiceGateway={gateway}
      contactsLoader={async () => [{ id: '1', name: 'Amina', phoneNumber: '08098765432' }]}
    />,
  );
  await fireEvent.press(screen.getByTestId('open-contacts'));
  await waitFor(() => expect(screen.getByText('Amina')).toBeTruthy());
  await fireEvent.press(screen.getByText('Amina'));
  await waitFor(() => expect(eligibility).toHaveBeenCalled());

  expect(screen.getByText('Call free')).toBeTruthy();
  await fireEvent.press(screen.getByTestId('start-call'));
  await waitFor(() => expect(onStarted).toHaveBeenCalledWith(call, 'Amina'));
});

it('AC-14.6: no connectivity shows the exact banner and disables calling', async () => {
  network.mockReturnValue({ connected: false, quality: 'poor' });
  await render(
    <DialPadScreen accessToken="access" pstnMinutesRemaining={10} onCallStarted={jest.fn()} />,
  );
  expect(screen.getByText('Calling requires an internet connection')).toBeTruthy();
  expect(screen.getByTestId('start-call').props.accessibilityState.disabled).toBe(true);
});

it('AC-14.7: low minutes warn without blocking a valid PSTN call', async () => {
  eligibility.mockResolvedValue({
    allowed: true,
    call_type: 'pstn',
    destination: '+2348098765432',
    reason: null,
    pstn_minutes_remaining: 4.5,
  });
  await render(
    <DialPadScreen accessToken="access" pstnMinutesRemaining={4.5} onCallStarted={jest.fn()} />,
  );
  expect(screen.getByText('Only 4.5 PSTN minutes remaining')).toBeTruthy();
  await enterNumber();
  expect(screen.getByTestId('start-call').props.accessibilityState.disabled).toBe(false);
});
