import React from 'react';
import {act, fireEvent, render} from '@testing-library/react-native';
import {Linking} from 'react-native';
import {SosSentScreen} from './SosSentScreen';

it('AC-16.4: shows honest sync state and calls the native dialer, never VoIP', async () => {
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  const view = await render(<SosSentScreen synced={false} htoPhone="+2348099999999" timestamp="2026-07-16T08:05:00Z" onCancel={jest.fn()} />);
  expect(view.getByText('SOS sent — help is coming')).toBeTruthy();
  expect(view.getByText('Sending... will notify your operator and family as soon as you have signal')).toBeTruthy();
  fireEvent.press(view.getByRole('button', {name: 'Call now'}));
  expect(open).toHaveBeenCalledWith('tel:+2348099999999');
});

it('AC-16.5: cancellation requires a separate custom confirmation', async () => {
  const onCancel = jest.fn();
  const view = await render(<SosSentScreen synced htoPhone="+2348099999999" timestamp="2026-07-16T08:05:00Z" onCancel={onCancel} />);
  await act(async () => fireEvent.press(view.getByRole('button', {name: 'Cancel SOS'})));
  expect(view.getByText('Are you sure you want to cancel this SOS?')).toBeTruthy();
  expect(onCancel).not.toHaveBeenCalled();
  await act(async () => fireEvent.press(view.getByRole('button', {name: 'Confirm cancellation'})));
  expect(onCancel).toHaveBeenCalledTimes(1);
});
