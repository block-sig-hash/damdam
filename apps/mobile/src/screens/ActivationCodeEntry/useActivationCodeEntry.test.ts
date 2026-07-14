import { act, renderHook } from '@testing-library/react-native';
import { ActivationApiError, previewActivationCode } from '../../api/activationClient';
import { useActivationCodeEntry } from './useActivationCodeEntry';

jest.mock('../../api/activationClient', () => {
  const actual = jest.requireActual('../../api/activationClient');
  return { ...actual, previewActivationCode: jest.fn() };
});

const mockPreview = previewActivationCode as jest.MockedFunction<
  typeof previewActivationCode
>;

beforeEach(() => {
  mockPreview.mockReset();
});

describe('useActivationCodeEntry', () => {
  it('seeds and normalizes an initial code from a deep link', async () => {
    const { result } = await renderHook(() =>
      useActivationCodeEntry({ initialCode: 'ab-cd 1234' }),
    );

    expect(result.current.code).toBe('ABCD1234');
  });

  it('marks a valid code as continue-able and exposes the preview (AC-07.2)', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    const { result } = await renderHook(() => useActivationCodeEntry({}));

    await act(async () => {
      result.current.setCode('ABCD1234');
    });
    await act(async () => {
      await result.current.checkCode();
    });

    expect(mockPreview).toHaveBeenCalledWith('ABCD1234');
    expect(result.current.canContinue).toBe(true);
    expect(result.current.preview?.organization_name).toBe('Barakah Hajj Services');
  });

  it('blocks continuing on an already-used code with a specific message', async () => {
    mockPreview.mockResolvedValue({
      valid: false,
      reason: 'activation_code_already_used',
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    const { result } = await renderHook(() => useActivationCodeEntry({}));

    await act(async () => {
      result.current.setCode('ABCD1234');
    });
    await act(async () => {
      await result.current.checkCode();
    });

    expect(result.current.canContinue).toBe(false);
    expect(result.current.errorMessage).toBe(
      'This activation code has already been used.',
    );
  });

  it('blocks continuing on an expired code with a specific message', async () => {
    mockPreview.mockResolvedValue({
      valid: false,
      reason: 'activation_code_expired',
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    const { result } = await renderHook(() => useActivationCodeEntry({}));

    await act(async () => {
      result.current.setCode('ABCD1234');
    });
    await act(async () => {
      await result.current.checkCode();
    });

    expect(result.current.errorMessage).toBe(
      'This activation code has expired. Ask your HTO for a new one.',
    );
  });

  it('surfaces an unknown code with a friendly message', async () => {
    mockPreview.mockRejectedValue(
      new ActivationApiError('activation_code_invalid', 'Invalid.'),
    );
    const { result } = await renderHook(() => useActivationCodeEntry({}));

    await act(async () => {
      result.current.setCode('NOTAREAL');
    });
    await act(async () => {
      await result.current.checkCode();
    });

    expect(result.current.canContinue).toBe(false);
    expect(result.current.errorMessage).toBe(
      "That code doesn't look right. Check it and try again.",
    );
  });

  it('does not check an incomplete code', async () => {
    const { result } = await renderHook(() => useActivationCodeEntry({}));

    await act(async () => {
      result.current.setCode('ABCD');
    });
    await act(async () => {
      await result.current.checkCode();
    });

    expect(mockPreview).not.toHaveBeenCalled();
  });

  it('resets status and preview when the code is edited again', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    const { result } = await renderHook(() => useActivationCodeEntry({}));

    await act(async () => {
      result.current.setCode('ABCD1234');
    });
    await act(async () => {
      await result.current.checkCode();
    });
    expect(result.current.canContinue).toBe(true);

    await act(async () => {
      result.current.setCode('ABCD1235');
    });

    expect(result.current.canContinue).toBe(false);
    expect(result.current.preview).toBeNull();
  });
});
