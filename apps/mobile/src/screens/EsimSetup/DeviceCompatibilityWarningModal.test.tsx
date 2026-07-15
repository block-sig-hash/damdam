import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { DeviceCompatibilityWarningModal } from './DeviceCompatibilityWarningModal';

describe('DeviceCompatibilityWarningModal', () => {
  it('AC-10.3: renders the exact warning copy when visible', async () => {
    await render(
      <DeviceCompatibilityWarningModal
        visible
        onContinue={jest.fn()}
        onSupport={jest.fn()}
      />,
    );

    expect(
      screen.getByText(
        'Your device does not appear to support eSIM. You can still use your DamDam ' +
          'package by scanning the QR code on a compatible device. Tap Continue to ' +
          'download your QR code, or tap Support to get help.',
      ),
    ).toBeTruthy();
  });

  it('AC-10.4: Continue calls onContinue', async () => {
    const onContinue = jest.fn();
    await render(
      <DeviceCompatibilityWarningModal visible onContinue={onContinue} onSupport={jest.fn()} />,
    );

    fireEvent.press(screen.getByTestId('esim-warning-continue'));

    expect(onContinue).toHaveBeenCalledTimes(1);
  });

  it('AC-10.5: Support calls onSupport', async () => {
    const onSupport = jest.fn();
    await render(
      <DeviceCompatibilityWarningModal visible onContinue={jest.fn()} onSupport={onSupport} />,
    );

    fireEvent.press(screen.getByTestId('esim-warning-support'));

    expect(onSupport).toHaveBeenCalledTimes(1);
  });

  it('passes visible=false through to the underlying Modal when not shown', async () => {
    await render(
      <DeviceCompatibilityWarningModal
        visible={false}
        onContinue={jest.fn()}
        onSupport={jest.fn()}
      />,
    );

    const modal = screen.queryByTestId('device-compatibility-warning-modal');
    if (modal) {
      expect(modal.props.visible).toBe(false);
    }
  });
});
