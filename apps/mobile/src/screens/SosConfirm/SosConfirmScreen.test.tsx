import React from 'react';
import {act, fireEvent, render} from '@testing-library/react-native';
import {SosConfirmScreen} from './SosConfirmScreen';

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

it('AC-16.1/16.2: requires a complete three-second hold and shows the countdown', async () => {
  const onConfirmed = jest.fn().mockResolvedValue(undefined);
  const view = await render(<SosConfirmScreen onConfirmed={onConfirmed} />);
  const button = view.getByRole('button', {name: 'SOS / Emergency'});
  expect(button.props.accessibilityHint).toContain('hold for 3 seconds');
  await fireEvent(button, 'pressIn');
  expect(view.getByText('3')).toBeTruthy();
  await act(async () => jest.advanceTimersByTimeAsync(2999));
  await fireEvent(button, 'pressOut');
  expect(onConfirmed).not.toHaveBeenCalled();
  await fireEvent(button, 'pressIn');
  await act(async () => jest.advanceTimersByTimeAsync(3000));
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});
