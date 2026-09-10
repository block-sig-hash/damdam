import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { setPin } from '../../api/pinClient';
import { savePinLocally } from '../../utils/pinLocalStore';
import { PinSetupScreen } from './PinSetupScreen';

const TEST_USER_ID = '11111111-1111-4111-8111-111111111111';

jest.mock('../../api/pinClient', () => {
  const actual = jest.requireActual('../../api/pinClient');
  return { ...actual, setPin: jest.fn() };
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
  mockSaveLocally.mockResolvedValue(undefined);
});

describe('PinSetupScreen', () => {
  it('auto-advances from entry to confirmation on a strong 4-digit PIN (AC-02.1/02.2)', async () => {
    await render(<PinSetupScreen userId={TEST_USER_ID} accessToken="access-token" onPinSet={jest.fn()} />);

    expect(screen.getByText('Create your PIN')).toBeTruthy();

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '4682');
    });

    expect(screen.getByText('Confirm your PIN')).toBeTruthy();
    expect(mockSetPin).not.toHaveBeenCalled();
  });

  it('rejects a sequential PIN inline without ever calling the API (AC-02.1)', async () => {
    await render(<PinSetupScreen userId={TEST_USER_ID} accessToken="access-token" onPinSet={jest.fn()} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '1234');
    });

    expect(screen.getByTestId('pin-setup-error-banner')).toBeTruthy();
    expect(screen.getByText('Choose a non-repeated, non-sequential 4-digit PIN.')).toBeTruthy();
    expect(screen.getByText('Create your PIN')).toBeTruthy();
    expect(mockSetPin).not.toHaveBeenCalled();
  });

  it('sets the PIN and calls onPinSet when the confirmation matches (AC-02.2)', async () => {
    mockSetPin.mockResolvedValue({ message: 'PIN set' });
    const onPinSet = jest.fn();
    await render(<PinSetupScreen userId={TEST_USER_ID} accessToken="access-token" onPinSet={onPinSet} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '4682');
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '4682');
    });

    expect(mockSetPin).toHaveBeenCalledWith('access-token', '4682');
    expect(onPinSet).toHaveBeenCalled();
  });

  it('shows a mismatch error and restarts entry when confirmation does not match (AC-02.2)', async () => {
    await render(<PinSetupScreen userId={TEST_USER_ID} accessToken="access-token" onPinSet={jest.fn()} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '4682');
    });
    await act(async () => {
      fireEvent.changeText(screen.getByTestId('pin-setup-input'), '9317');
    });

    expect(screen.getByText("PINs didn't match. Try again.")).toBeTruthy();
    expect(screen.getByText('Create your PIN')).toBeTruthy();
    expect(mockSetPin).not.toHaveBeenCalled();
  });
});
