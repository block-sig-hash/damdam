import { act, renderHook } from '@testing-library/react-native';
import { PinApiError, setPin } from '../../api/pinClient';
import { usePinSetup } from './usePinSetup';

jest.mock('../../api/pinClient', () => {
  const actual = jest.requireActual('../../api/pinClient');
  return {
    ...actual,
    setPin: jest.fn(),
  };
});

const mockSetPin = setPin as jest.MockedFunction<typeof setPin>;

beforeEach(() => {
  mockSetPin.mockReset();
});

async function mount(onPinSet: jest.Mock) {
  return renderHook(() => usePinSetup({ accessToken: 'access-token', onPinSet }));
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

  it('sets the PIN and calls onPinSet when the confirmation matches (AC-02.2)', async () => {
    mockSetPin.mockResolvedValue({ message: 'PIN set' });
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
    expect(onPinSet).toHaveBeenCalled();
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
