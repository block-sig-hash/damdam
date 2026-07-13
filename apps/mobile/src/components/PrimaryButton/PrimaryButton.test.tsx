import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { PrimaryButton } from './PrimaryButton';

describe('PrimaryButton', () => {
  it('calls onPress when tapped', async () => {
    const onPress = jest.fn();
    await render(<PrimaryButton label="Send code" onPress={onPress} />);

    await fireEvent.press(screen.getByRole('button', { name: 'Send code' }));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('does not call onPress when disabled', async () => {
    const onPress = jest.fn();
    await render(<PrimaryButton label="Send code" onPress={onPress} disabled />);

    await fireEvent.press(screen.getByRole('button', { name: 'Send code' }));

    expect(onPress).not.toHaveBeenCalled();
  });

  it('shows a loading indicator instead of the label while loading', async () => {
    await render(<PrimaryButton label="Send code" onPress={jest.fn()} loading />);

    expect(screen.queryByText('Send code')).toBeNull();
  });
});
