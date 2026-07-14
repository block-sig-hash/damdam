import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { requestPinRecovery, verifyPinRecovery } from '../../api/authClient';
import {
  clearLocalPinLock,
  getLocalPinState,
  recordFailedPinAttempt,
  verifyPinLocally,
} from '../../utils/pinLocalStore';
import { PinUnlockScreen } from './PinUnlockScreen';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return { ...actual, requestPinRecovery: jest.fn(), verifyPinRecovery: jest.fn() };
});
jest.mock('../../utils/pinLocalStore', () => ({
  ...jest.requireActual('../../utils/pinLocalStore'),
  getLocalPinState: jest.fn(),
  verifyPinLocally: jest.fn(),
  recordFailedPinAttempt: jest.fn(),
  clearLocalPinLock: jest.fn(),
}));

const mockGetState = getLocalPinState as jest.MockedFunction<typeof getLocalPinState>;
const mockVerify = verifyPinLocally as jest.MockedFunction<typeof verifyPinLocally>;
const mockRecordFailure = recordFailedPinAttempt as jest.MockedFunction<
  typeof recordFailedPinAttempt
>;
const mockClearLock = clearLocalPinLock as jest.MockedFunction<typeof clearLocalPinLock>;
const mockRequestRecovery = requestPinRecovery as jest.MockedFunction<
  typeof requestPinRecovery
>;
const mockVerifyRecovery = verifyPinRecovery as jest.MockedFunction<typeof verifyPinRecovery>;

beforeEach(() => {
  mockGetState.mockReset();
  mockVerify.mockReset();
  mockRecordFailure.mockReset();
  mockClearLock.mockReset();
  mockRequestRecovery.mockReset();
  mockVerifyRecovery.mockReset();
});

describe('PinUnlockScreen', () => {
  it('unlocks with no network call on a correct PIN (AC-02.3/AC-23.3)', async () => {
    mockGetState.mockResolvedValue({ pin: '4682', failedAttempts: 0, lockedUntil: null });
    mockVerify.mockResolvedValue(true);
    const onUnlocked = jest.fn();

    await act(async () => {
      render(<PinUnlockScreen phoneNumber="08012345678" onUnlocked={onUnlocked} />);
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-unlock-input'), '4682');
    });

    expect(mockVerify).toHaveBeenCalledWith('4682');
    expect(onUnlocked).toHaveBeenCalledWith();
    expect(mockRequestRecovery).not.toHaveBeenCalled();
  });

  it('shows an inline error on a wrong PIN without locking out early', async () => {
    mockGetState.mockResolvedValue({ pin: '4682', failedAttempts: 0, lockedUntil: null });
    mockVerify.mockResolvedValue(false);
    mockRecordFailure.mockResolvedValue({ pin: '4682', failedAttempts: 1, lockedUntil: null });

    await act(async () => {
      render(<PinUnlockScreen phoneNumber="08012345678" onUnlocked={jest.fn()} />);
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-unlock-input'), '0000');
    });

    expect(screen.getByTestId('pin-unlock-error-banner')).toBeTruthy();
    expect(screen.getByText('Incorrect PIN. 4 attempts left.')).toBeTruthy();
  });

  it('locks after the 5th failed attempt and shows the countdown (AC-02.4/AC-23.5)', async () => {
    mockGetState.mockResolvedValue({ pin: '4682', failedAttempts: 4, lockedUntil: null });
    mockVerify.mockResolvedValue(false);
    mockRecordFailure.mockResolvedValue({
      pin: '4682',
      failedAttempts: 5,
      lockedUntil: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
    });

    await act(async () => {
      render(<PinUnlockScreen phoneNumber="08012345678" onUnlocked={jest.fn()} />);
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-unlock-input'), '0000');
    });

    expect(screen.getByText(/Too many attempts\. Try again in/)).toBeTruthy();
    expect(screen.getByTestId('pin-unlock-submit').props.accessibilityState.disabled).toBe(true);
  });

  it('offers OTP recovery immediately, even before any failed attempt (AC-02.4)', async () => {
    mockGetState.mockResolvedValue({ pin: '4682', failedAttempts: 0, lockedUntil: null });
    mockRequestRecovery.mockResolvedValue({ message: 'OTP sent' });
    mockVerifyRecovery.mockResolvedValue({
      access_token: 'access-token',
      refresh_token: 'refresh-token',
      is_new_user: false,
      user: {
        id: 'user-1',
        phone_number: '+2348012345678',
        first_name: '',
        last_name: '',
        email: null,
        verified_cli: true,
        platform: 'android',
        status: 'active',
      },
    });
    mockClearLock.mockResolvedValue(undefined);
    const onUnlocked = jest.fn();

    await act(async () => {
      render(<PinUnlockScreen phoneNumber="08012345678" onUnlocked={onUnlocked} />);
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('pin-unlock-recovery-link'));
    });

    expect(mockRequestRecovery).toHaveBeenCalledWith('08012345678');
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('otp-code-input'), '123456');
    });

    expect(mockClearLock).toHaveBeenCalled();
    expect(onUnlocked).toHaveBeenCalledWith(
      expect.objectContaining({ access_token: 'access-token' }),
    );
  });

  it('routes straight to recovery when no local PIN is stored (AC-23.4 new-device case)', async () => {
    mockGetState.mockResolvedValue(null);

    await act(async () => {
      render(<PinUnlockScreen phoneNumber="08012345678" onUnlocked={jest.fn()} />);
    });

    expect(screen.queryByTestId('pin-unlock-input')).toBeNull();
    expect(screen.getByTestId('pin-unlock-start-recovery')).toBeTruthy();
  });
});
