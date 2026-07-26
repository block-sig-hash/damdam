import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react-native';
import { Banner } from './Banner';

describe('Banner', () => {
  it('renders the message without an action by default', async () => {
    await render(<Banner tone="info" message="Informational text" testID="banner" />);
    expect(screen.getByText('Informational text')).toBeTruthy();
    expect(screen.queryByTestId('banner-action')).toBeNull();
  });

  it('renders and triggers the optional trailing action', async () => {
    const onAction = jest.fn();
    await render(
      <Banner
        tone="info"
        message="Verify your number"
        actionLabel="Verify now"
        onAction={onAction}
        testID="banner"
      />,
    );

    const action = screen.getByTestId('banner-action');
    expect(action).toBeTruthy();
    await fireEvent.press(action);
    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
