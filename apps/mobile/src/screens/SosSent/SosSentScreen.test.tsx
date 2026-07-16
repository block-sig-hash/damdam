import React from 'react';
import {fireEvent, Linking, render, screen} from '@testing-library/react-native';
import {SosSentScreen} from './SosSentScreen';

it('AC-16.4: shows honest sync state and calls the native dialer, never VoIP', () => {
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
  render(<SosSentScreen synced={false} htoPhone="+2348099999999" timestamp="2026-07-16T08:05:00Z" onCancel={jest.fn()} />);
  expect(screen.getByText('SOS sent — help is coming')).toBeTruthy();
  expect(screen.getByText('Sending... will notify your operator and family as soon as you have signal')).toBeTruthy();
  fireEvent.press(screen.getByRole('button', {name: 'Call now'}));
  expect(open).toHaveBeenCalledWith('tel:+2348099999999');
});

it('AC-16.5: cancellation requires a separate custom confirmation', () => {
  const onCancel = jest.fn();
  render(<SosSentScreen synced htoPhone="+2348099999999" timestamp="2026-07-16T08:05:00Z" onCancel={onCancel} />);
  fireEvent.press(screen.getByRole('button', {name: 'Cancel SOS'}));
  expect(screen.getByText('Are you sure you want to cancel this SOS?')).toBeTruthy();
  expect(onCancel).not.toHaveBeenCalled();
  fireEvent.press(screen.getByRole('button', {name: 'Confirm cancellation'}));
  expect(onCancel).toHaveBeenCalledTimes(1);
});

