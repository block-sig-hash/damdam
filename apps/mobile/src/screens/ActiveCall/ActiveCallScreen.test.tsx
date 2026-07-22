import React from 'react';
import { act, render, screen } from '@testing-library/react-native';
import { useNetworkQuality } from '../../hooks/useNetworkQuality';
import type { VoiceCallSession, VoiceCallState } from '../../services/voiceGateway';
import { ActiveCallScreen } from './ActiveCallScreen';

jest.mock('../../hooks/useNetworkQuality', () => ({ useNetworkQuality: jest.fn() }));

const network = useNetworkQuality as jest.MockedFunction<typeof useNetworkQuality>;

function fakeCall(callType: 'pstn' | 'app_to_app' = 'app_to_app'): VoiceCallSession {
  return {
    callType,
    displayNumber: '08098765432',
    subscribeState(listener: (state: VoiceCallState) => void) {
      listener('connected');
      return jest.fn();
    },
    subscribeDuration(listener: (seconds: number) => void) {
      listener(65);
      return jest.fn();
    },
    toggleMute: jest.fn().mockResolvedValue(true),
    toggleSpeaker: jest.fn().mockResolvedValue(true),
    hangup: jest.fn().mockResolvedValue(undefined),
  };
}

it('AC-14.5/8: shows duration, free call type, and signal quality during a call', async () => {
  network.mockReturnValue({ connected: true, quality: 'good' });
  await render(<ActiveCallScreen call={fakeCall()} recipientName="Amina" onFinished={jest.fn()} />);
  expect(screen.getByText('01:05')).toBeTruthy();
  expect(screen.getByText('DamDam-to-DamDam — free')).toBeTruthy();
  expect(screen.getByLabelText('Call quality good')).toBeTruthy();
});

it('allows the screenshot harness to replace the simulator network snapshot', async () => {
  network.mockReturnValue({ connected: false, quality: 'poor' });
  const call = fakeCall();
  await render(
    <ActiveCallScreen
      call={call}
      onFinished={jest.fn()}
      networkQualityOverride={{ connected: true, quality: 'excellent' }}
    />,
  );
  expect(screen.getByLabelText('Call quality excellent')).toBeTruthy();
  expect(call.hangup).not.toHaveBeenCalled();
});

it('AC-14.6: connectivity loss ends gracefully and returns after exactly 3 seconds', async () => {
  jest.useFakeTimers();
  network.mockReturnValue({ connected: false, quality: 'poor' });
  const call = fakeCall('pstn');
  const finished = jest.fn();
  await render(<ActiveCallScreen call={call} onFinished={finished} />);
  expect(screen.getByText('Call ended — connectivity lost')).toBeTruthy();
  expect(call.hangup).toHaveBeenCalled();
  await act(async () => jest.advanceTimersByTime(2999));
  expect(finished).not.toHaveBeenCalled();
  await act(async () => jest.advanceTimersByTime(1));
  expect(finished).toHaveBeenCalledTimes(1);
  jest.useRealTimers();
});

it('AC-14.6: an SDK-reported dropped call also returns after 3 seconds', async () => {
  jest.useFakeTimers();
  network.mockReturnValue({ connected: true, quality: 'good' });
  const call = fakeCall('pstn');
  call.subscribeState = (listener) => {
    listener('dropped');
    return jest.fn();
  };
  const finished = jest.fn();
  await render(<ActiveCallScreen call={call} onFinished={finished} />);
  expect(screen.getByText('Call ended — connectivity lost')).toBeTruthy();
  await act(async () => jest.advanceTimersByTime(3000));
  expect(finished).toHaveBeenCalledTimes(1);
  jest.useRealTimers();
});
