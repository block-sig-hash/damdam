import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';
import { requestOtp } from '../../api/authClient';
import { PhoneEntryScreen } from './PhoneEntryScreen';

jest.mock('../../api/authClient', () => {
  const actual = jest.requireActual('../../api/authClient');
  return { ...actual, requestOtp: jest.fn() };
});

const mockRequestOtp = requestOtp as jest.MockedFunction<typeof requestOtp>;

beforeEach(() => {
  mockRequestOtp.mockReset();
});

describe('PhoneEntryScreen', () => {
  it('can return to email sign-in when mounted from the signed-out navigator', async () => {
    const onCancel = jest.fn();
    await render(
      <PhoneEntryScreen
        onOtpSent={jest.fn()}
        onAccountExists={jest.fn()}
        onCancel={onCancel}
      />,
    );

    await act(async () => {
      fireEvent.press(screen.getByTestId('phone-entry-cancel'));
    });

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('disables Send code until a valid Nigerian number is entered (AC-01.1)', async () => {
    const onOtpSent = jest.fn();
    await render(<PhoneEntryScreen onOtpSent={onOtpSent} onAccountExists={jest.fn()} />);

    const submit = screen.getByTestId('phone-entry-submit');
    expect(submit.props.accessibilityState.disabled).toBe(true);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('phone-entry-input'), '08012345678');
    });

    expect(screen.getByTestId('phone-entry-submit').props.accessibilityState.disabled).toBe(
      false,
    );
  });

  it('sends the OTP request and calls onOtpSent (AC-01.3)', async () => {
    mockRequestOtp.mockResolvedValue({ message: 'OTP sent' });
    const onOtpSent = jest.fn();
    await render(<PhoneEntryScreen onOtpSent={onOtpSent} onAccountExists={jest.fn()} />);

    await act(async () => {
      fireEvent.changeText(screen.getByTestId('phone-entry-input'), '08012345678');
    });
    await act(async () => {
      fireEvent.press(screen.getByTestId('phone-entry-submit'));
    });

    expect(mockRequestOtp).toHaveBeenCalledWith('08012345678', 'en');
    expect(onOtpSent).toHaveBeenCalledWith('08012345678');
  });
});
