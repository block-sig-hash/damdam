import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { previewActivationCode } from '../../api/activationClient';
import { ActivationCodeEntryScreen } from './ActivationCodeEntryScreen';

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

describe('ActivationCodeEntryScreen', () => {
  it('auto-checks a code typed to full length and shows the preview (AC-07.2)', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    await render(<ActivationCodeEntryScreen onContinue={jest.fn()} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('activation-code-input'), 'abcd1234');
    });

    expect(mockPreview).toHaveBeenCalledWith('ABCD1234');
    expect(screen.getByTestId('activation-preview-card')).toBeTruthy();
    expect(screen.getByText('Barakah Hajj Services')).toBeTruthy();
    expect(screen.getByTestId('activation-code-continue').props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: false }),
    );
  });

  it('auto-checks a code pre-filled from a deep link on mount', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });

    await act(async () => {
      render(
        <ActivationCodeEntryScreen initialCode="ABCD1234" onContinue={jest.fn()} />,
      );
    });

    expect(mockPreview).toHaveBeenCalledWith('ABCD1234');
    expect(await screen.findByTestId('activation-preview-card')).toBeTruthy();
  });

  it('shows an error banner and disables Continue for an already-used code', async () => {
    mockPreview.mockResolvedValue({
      valid: false,
      reason: 'activation_code_already_used',
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    await render(<ActivationCodeEntryScreen onContinue={jest.fn()} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('activation-code-input'), 'ABCD1234');
    });

    expect(screen.getByTestId('activation-code-error')).toBeTruthy();
    expect(screen.getByTestId('activation-code-continue').props.accessibilityState).toEqual(
      expect.objectContaining({ disabled: true }),
    );
  });

  it('calls onContinue with the checked code when Continue is pressed', async () => {
    mockPreview.mockResolvedValue({
      valid: true,
      reason: null,
      organization_name: 'Barakah Hajj Services',
      pricing_tier_name: 'Standard',
    });
    const onContinue = jest.fn();
    await render(<ActivationCodeEntryScreen onContinue={onContinue} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('activation-code-input'), 'ABCD1234');
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('activation-code-continue'));
    });

    expect(onContinue).toHaveBeenCalledWith('ABCD1234');
  });
});
