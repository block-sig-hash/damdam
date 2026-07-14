import React from 'react';
import { render, screen } from '@testing-library/react-native';
import { OtpCodeInput } from './OtpCodeInput';

describe('OtpCodeInput', () => {
  it('shows the raw digit by default (OTP mode)', async () => {
    await render(
      <OtpCodeInput length={6} value="123" onChangeValue={jest.fn()} testID="code-input" />,
    );

    expect(screen.getByText('1')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
  });

  it('masks entered digits when masked (AC-02.2)', async () => {
    await render(
      <OtpCodeInput
        length={4}
        value="12"
        onChangeValue={jest.fn()}
        masked
        testID="pin-input"
      />,
    );

    expect(screen.queryByText('1')).toBeNull();
    expect(screen.queryByText('2')).toBeNull();
    expect(screen.getAllByText('•')).toHaveLength(2);
  });
});
