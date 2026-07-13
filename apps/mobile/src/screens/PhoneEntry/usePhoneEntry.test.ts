import { act, renderHook } from '@testing-library/react-native';
import { OtpApiError, requestOtp } from '../../api/authClient';
import { usePhoneEntry } from './usePhoneEntry';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return { ...actual, requestOtp: jest.fn() };
});

const mockRequestOtp = requestOtp as jest.MockedFunction<typeof requestOtp>;

beforeEach(() => {
  mockRequestOtp.mockReset();
});

describe('usePhoneEntry', () => {
  it('is invalid until an 11-digit Nigerian number is entered (AC-01.1/AC-01.2)', async () => {
    const { result } = await renderHook(() =>
      usePhoneEntry({ onOtpSent: jest.fn(), onAccountExists: jest.fn() }),
    );

    expect(result.current.isValid).toBe(false);

    await act(async () => {
      result.current.setPhoneNumber('0801234567');
    });
    expect(result.current.isValid).toBe(false);

    await act(async () => {
      result.current.setPhoneNumber('08012345678');
    });
    expect(result.current.isValid).toBe(true);
  });

  it('rejects a non-Nigerian-prefix number', async () => {
    const { result } = await renderHook(() =>
      usePhoneEntry({ onOtpSent: jest.fn(), onAccountExists: jest.fn() }),
    );

    await act(async () => {
      result.current.setPhoneNumber('07112345678');
    });

    expect(result.current.isValid).toBe(false);
  });

  it('requests an OTP and calls onOtpSent on success (AC-01.3)', async () => {
    mockRequestOtp.mockResolvedValue({ message: 'OTP sent' });
    const onOtpSent = jest.fn();
    const { result } = await renderHook(() =>
      usePhoneEntry({ onOtpSent, onAccountExists: jest.fn() }),
    );

    await act(async () => {
      result.current.setPhoneNumber('08012345678');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(mockRequestOtp).toHaveBeenCalledWith('08012345678');
    expect(onOtpSent).toHaveBeenCalledWith('08012345678');
  });

  it('does not call requestOtp while the number is invalid', async () => {
    const { result } = await renderHook(() =>
      usePhoneEntry({ onOtpSent: jest.fn(), onAccountExists: jest.fn() }),
    );

    await act(async () => {
      await result.current.submit();
    });

    expect(mockRequestOtp).not.toHaveBeenCalled();
  });

  it('directs an existing account to login instead of showing an error (AC-01.7)', async () => {
    mockRequestOtp.mockRejectedValue(new OtpApiError('account_exists', 'Please log in.'));
    const onAccountExists = jest.fn();
    const { result } = await renderHook(() =>
      usePhoneEntry({ onOtpSent: jest.fn(), onAccountExists }),
    );

    await act(async () => {
      result.current.setPhoneNumber('08012345678');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(onAccountExists).toHaveBeenCalledWith('08012345678');
    expect(result.current.errorMessage).toBeNull();
  });

  it('surfaces other API errors inline', async () => {
    mockRequestOtp.mockRejectedValue(
      new OtpApiError('otp_unavailable', 'Verification is temporarily unavailable.'),
    );
    const { result } = await renderHook(() =>
      usePhoneEntry({ onOtpSent: jest.fn(), onAccountExists: jest.fn() }),
    );

    await act(async () => {
      result.current.setPhoneNumber('08012345678');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.errorMessage).toBe('Verification is temporarily unavailable.');
  });
});
