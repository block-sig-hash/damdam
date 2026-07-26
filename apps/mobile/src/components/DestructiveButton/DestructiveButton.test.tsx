import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { DestructiveButton } from './DestructiveButton';

describe('DestructiveButton', () => {
  it('calls onPress when enabled', async () => {
    const onPress = jest.fn();
    await render(<DestructiveButton label="Revoke" onPress={onPress} testID="destructive" />);

    await fireEvent.press(screen.getByTestId('destructive'));
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it('does not call onPress when disabled', async () => {
    const onPress = jest.fn();
    await render(
      <DestructiveButton label="Revoke" onPress={onPress} disabled testID="destructive" />,
    );

    await fireEvent.press(screen.getByTestId('destructive'));
    expect(onPress).not.toHaveBeenCalled();
    expect(screen.getByTestId('destructive').props.accessibilityState.disabled).toBe(true);
  });

  it('shows a loading indicator instead of the label while loading', async () => {
    await render(<DestructiveButton label="Revoke" onPress={jest.fn()} loading testID="destructive" />);
    expect(screen.queryByText('Revoke')).toBeNull();
  });
});
