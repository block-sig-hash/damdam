import React from 'react';
import {act, fireEvent, render, screen} from '@testing-library/react-native';
import {SosConfirmScreen} from './SosConfirmScreen';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it('AC-16.1/16.2: requires a complete three-second hold and shows the countdown', async () => {
  const onConfirmed = jest.fn().mockResolvedValue(undefined);
  render(<SosConfirmScreen onConfirmed={onConfirmed} />);
  const button = screen.getByRole('button', {name: 'SOS / Emergency'});
  expect(button.props.accessibilityHint).toContain('hold for 3 seconds');
  fireEvent(button, 'pressIn');
  expect(screen.getByText('3')).toBeTruthy();
  await act(async () => jest.advanceTimersByTimeAsync(2999));
  fireEvent(button, 'pressOut');
  expect(onConfirmed).not.toHaveBeenCalled();
  fireEvent(button, 'pressIn');
  await act(async () => jest.advanceTimersByTimeAsync(3000));
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

