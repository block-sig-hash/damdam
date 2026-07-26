import { act, renderHook } from '@testing-library/react-native';
import {
  OtpApiError,
  requestPinRecovery,
  verifyPinRecovery,
} from '../../api/authClient';
import { useReturningPilgrimLogin } from './useReturningPilgrimLogin';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return { ...actual, requestPinRecovery: jest.fn(), verifyPinRecovery: jest.fn() };
});

const mockRequest = requestPinRecovery as jest.MockedFunction<typeof requestPinRecovery>;
const mockVerify = verifyPinRecovery as jest.MockedFunction<typeof verifyPinRecovery>;

const AUTH_RESPONSE = {
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
    locale: 'en' as const,
    platform: 'android',
    status: 'active',
  },
};

beforeEach(() => {
  mockRequest.mockReset();
  mockVerify.mockReset();
});

describe('useReturningPilgrimLogin', () => {
  it('sends the recovery code automatically on mount (AC-23.4)', async () => {
    mockRequest.mockResolvedValue({ message: 'OTP sent' });
    const { result } = await renderHook(() =>
      useReturningPilgrimLogin({
        phoneNumber: '08012345678',
        platform: 'android',
        onVerified: jest.fn(),
      }),
    );

    expect(mockRequest).toHaveBeenCalledWith('08012345678', 'en');
    expect(result.current.status).toBe('awaiting_code');
  });

  it('verifies the code and calls onVerified (AC-01.7/AC-07.5)', async () => {
    mockRequest.mockResolvedValue({ message: 'OTP sent' });
    mockVerify.mockResolvedValue(AUTH_RESPONSE);
    const onVerified = jest.fn();
    const { result } = await renderHook(() =>
      useReturningPilgrimLogin({
        phoneNumber: '08012345678',
        platform: 'android',
        onVerified,
      }),
    );

    await act(async () => {
      result.current.setCode('123456');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(mockVerify).toHaveBeenCalledWith('08012345678', '123456', 'android', 'en');
    expect(onVerified).toHaveBeenCalledWith(AUTH_RESPONSE);
  });

  it('locks out after too many attempts', async () => {
    mockRequest.mockResolvedValue({ message: 'OTP sent' });
    mockVerify.mockRejectedValue(
      new OtpApiError('locked', 'Too many attempts. Please wait before trying again.', 60),
    );
    const { result } = await renderHook(() =>
      useReturningPilgrimLogin({
        phoneNumber: '08012345678',
        platform: 'android',
        onVerified: jest.fn(),
      }),
    );

    await act(async () => {
      result.current.setCode('000000');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.status).toBe('locked');
  });

  it('surfaces a failed initial send without crashing and allows resend', async () => {
    mockRequest.mockRejectedValueOnce(
      new OtpApiError('rate_limited', 'Please wait before requesting another code.', 30),
    );
    const { result } = await renderHook(() =>
      useReturningPilgrimLogin({
        phoneNumber: '08012345678',
        platform: 'android',
        onVerified: jest.fn(),
      }),
    );

    expect(result.current.status).toBe('awaiting_code');
    expect(result.current.errorMessage).toBe('Please wait before requesting another code.');
  });
});
