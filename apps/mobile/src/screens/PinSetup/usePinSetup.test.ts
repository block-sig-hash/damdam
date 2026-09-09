import { act, renderHook } from '@testing-library/react-native';
import { PinApiError, setPin } from '../../api/pinClient';
import { savePinLocally } from '../../utils/pinLocalStore';
import { usePinSetup } from './usePinSetup';

const TEST_USER_ID = '11111111-1111-4111-8111-111111111111';

jest.mock('../../api/pinClient', () => {
  const actual = jest.requireActual('../../api/pinClient');
  return {
    ...actual,
    setPin: jest.fn(),
  };
});
jest.mock('../../utils/pinLocalStore', () => ({
  ...jest.requireActual('../../utils/pinLocalStore'),
  savePinLocally: jest.fn(),
}));

const mockSetPin = setPin as jest.MockedFunction<typeof setPin>;
const mockSaveLocally = savePinLocally as jest.MockedFunction<typeof savePinLocally>;

beforeEach(() => {
  mockSetPin.mockReset();
  mockSaveLocally.mockReset();
});

async function mount(onPinSet: jest.Mock) {
  return renderHook(() => usePinSetup({ accessToken: 'access-token',
    userId: TEST_USER_ID, onPinSet }));
}

describe('usePinSetup', () => {
  it('rejects a weak PIN before ever reaching the confirm stage (AC-02.1)', async () => {
    const onPinSet = jest.fn();
    const { result } = await mount(onPinSet);

    await act(async () => {
      result.current.setValue('1234');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.stage).toBe('enter');
    expect(result.current.value).toBe('');
    expect(result.current.errorMessage).toBe(
      'Choose a non-repeated, non-sequential 4-digit PIN.',
    );
    expect(mockSetPin).not.toHaveBeenCalled();
  });

  it('advances to the confirm stage on a strong PIN without calling the API yet (AC-02.2)', async () => {
    const onPinSet = jest.fn();
    const { result } = await mount(onPinSet);

    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.stage).toBe('confirm');
    expect(result.current.value).toBe('');
    expect(mockSetPin).not.toHaveBeenCalled();
  });

  it('sets the PIN, saves it locally for PIN Unlock, and calls onPinSet on match (AC-02.2)', async () => {
    mockSetPin.mockResolvedValue({ message: 'PIN set' });
    mockSaveLocally.mockResolvedValue(undefined);
    const onPinSet = jest.fn();
    const { result } = await mount(onPinSet);

    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(mockSetPin).toHaveBeenCalledWith('access-token', '4682');
    expect(mockSaveLocally).toHaveBeenCalledWith(TEST_USER_ID, '4682');
    expect(onPinSet).toHaveBeenCalled();
  });

  it('still completes onboarding if the local Keychain save fails (best-effort)', async () => {
    mockSetPin.mockResolvedValue({ message: 'PIN set' });
    mockSaveLocally.mockRejectedValue(new Error('Keychain unavailable'));
    const onPinSet = jest.fn();
    const { result } = await mount(onPinSet);

    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(mockSaveLocally).toHaveBeenCalledWith(TEST_USER_ID, '4682');
    expect(onPinSet).toHaveBeenCalled();
    expect(result.current.errorMessage).toBeNull();
  });

  it('restarts at the enter stage with an error when the confirmation does not match (AC-02.2)', async () => {
    const onPinSet = jest.fn();
    const { result } = await mount(onPinSet);

    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      result.current.setValue('9317');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.stage).toBe('enter');
    expect(result.current.value).toBe('');
    expect(result.current.errorMessage).toBe("PINs didn't match. Try again.");
    expect(mockSetPin).not.toHaveBeenCalled();
    expect(onPinSet).not.toHaveBeenCalled();
  });

  it('surfaces a server-side rejection and restarts at the enter stage', async () => {
    mockSetPin.mockRejectedValue(
      new PinApiError('pin_too_weak', 'Choose a non-repeated, non-sequential 4-digit PIN.'),
    );
    const onPinSet = jest.fn();
    const { result } = await mount(onPinSet);

    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });
    await act(async () => {
      result.current.setValue('4682');
    });
    await act(async () => {
      await result.current.submit();
    });

    expect(result.current.stage).toBe('enter');
    expect(result.current.errorMessage).toBe(
      'Choose a non-repeated, non-sequential 4-digit PIN.',
    );
    expect(onPinSet).not.toHaveBeenCalled();
  });
});
