import { act, renderHook } from '@testing-library/react-native';
import { AuthResponse, OtpApiError, requestOtp, verifyOtp } from '../../api/authClient';
import { useOtpVerification } from './useOtpVerification';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return {
    ...actual,
    requestOtp: jest.fn(),
    verifyOtp: jest.fn(),
  };
});

const mockRequestOtp = requestOtp as jest.MockedFunction<typeof requestOtp>;
const mockVerifyOtp = verifyOtp as jest.MockedFunction<typeof verifyOtp>;

const AUTH_RESPONSE: AuthResponse = {
  access_token: 'access-token',
  refresh_token: 'refresh-token',
  is_new_user: true,
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
};

beforeEach(() => {
  jest.useFakeTimers();
  mockRequestOtp.mockReset();
  mockVerifyOtp.mockReset();
});

afterEach(() => {
  jest.useRealTimers();
});

async function mount(onVerified: jest.Mock) {
  return renderHook(() =>
    useOtpVerification({ phoneNumber: '08012345678', platform: 'android', onVerified }),
  );
}

describe('useOtpVerification', () => {
  it('does not show the sending reassurance state before 10 seconds', async () => {
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      jest.advanceTimersByTime(9_000);
    });

    expect(result.current.showSendingReassurance).toBe(false);
  });

  it('shows the sending reassurance state after 10 seconds (AC-01.9)', async () => {
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      jest.advanceTimersByTime(10_000);
    });

    expect(result.current.showSendingReassurance).toBe(true);
  });

  it('enables manual resend only from 30 seconds, not before (AC-01.9)', async () => {
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      jest.advanceTimersByTime(29_000);
    });
    expect(result.current.canResend).toBe(false);

    await act(async () => {
      jest.advanceTimersByTime(1_000);
    });
    expect(result.current.canResend).toBe(true);
  });

  it('verifies the code and calls onVerified on success (AC-01.6)', async () => {
    mockVerifyOtp.mockResolvedValue(AUTH_RESPONSE);
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      result.current.setCode('123456');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(mockVerifyOtp).toHaveBeenCalledWith('08012345678', '123456', 'android');
    expect(onVerified).toHaveBeenCalledWith(AUTH_RESPONSE);
  });

  it('shows an inline error and clears the code on an incorrect OTP (AC-01.5)', async () => {
    mockVerifyOtp.mockRejectedValue(
      new OtpApiError('invalid_otp', 'The verification code is incorrect.'),
    );
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      result.current.setCode('000000');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.status).toBe('awaiting_code');
    expect(result.current.code).toBe('');
    expect(result.current.errorMessage).toBe('That code is incorrect. Try again.');
  });

  it('locks out after a 423 response and counts down back to awaiting_code (AC-01.5)', async () => {
    mockVerifyOtp.mockRejectedValue(new OtpApiError('locked', 'Too many attempts.', 60));
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      result.current.setCode('000000');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.status).toBe('locked');
    expect(result.current.lockoutSecondsRemaining).toBe(60);

    await act(async () => {
      jest.advanceTimersByTime(59_000);
    });
    expect(result.current.status).toBe('locked');

    await act(async () => {
      jest.advanceTimersByTime(1_000);
    });
    expect(result.current.status).toBe('awaiting_code');
  });

  it('prompts a resend when the code has expired (AC-01.4)', async () => {
    mockVerifyOtp.mockRejectedValue(
      new OtpApiError('otp_expired', 'The verification code has expired.'),
    );
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      result.current.setCode('123456');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.status).toBe('awaiting_code');
    expect(result.current.errorMessage).toBe('That code expired. Send a new one.');
  });

  it('resends the code and resets the elapsed timer (AC-01.9)', async () => {
    mockRequestOtp.mockResolvedValue({ message: 'OTP sent' });
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      jest.advanceTimersByTime(30_000);
    });
    expect(result.current.canResend).toBe(true);

    await act(async () => {
      await result.current.resend();
    });

    expect(mockRequestOtp).toHaveBeenCalledWith('08012345678');
    expect(result.current.canResend).toBe(false);
    expect(result.current.showSendingReassurance).toBe(false);
  });

  it('blocks resend and surfaces the server cooldown on 429 (PRD §5.1)', async () => {
    mockRequestOtp.mockRejectedValue(
      new OtpApiError('rate_limited', 'Please wait before requesting another code.', 45),
    );
    const onVerified = jest.fn();
    const { result } = await mount(onVerified);

    await act(async () => {
      jest.advanceTimersByTime(30_000);
    });
    await act(async () => {
      await result.current.resend();
    });

    expect(result.current.canResend).toBe(false);
    expect(result.current.secondsUntilResend).toBe(45);
  });
});
