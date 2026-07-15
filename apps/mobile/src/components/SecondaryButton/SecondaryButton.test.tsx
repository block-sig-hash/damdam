import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { SecondaryButton } from './SecondaryButton';

describe('SecondaryButton', () => {
  it('calls onPress when tapped', async () => {
    const onPress = jest.fn();
    await render(<SecondaryButton label="Support" onPress={onPress} />);

    await fireEvent.press(screen.getByRole('button', { name: 'Support' }));

    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('does not call onPress when disabled', async () => {
    const onPress = jest.fn();
    await render(<SecondaryButton label="Support" onPress={onPress} disabled />);

    await fireEvent.press(screen.getByRole('button', { name: 'Support' }));

    expect(onPress).not.toHaveBeenCalled();
  });

  it('shows a loading indicator instead of the label while loading', async () => {
    await render(<SecondaryButton label="Support" onPress={jest.fn()} loading />);

    expect(screen.queryByText('Support')).toBeNull();
  });
});
