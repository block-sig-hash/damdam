import React from 'react';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react-native';
import {Linking} from 'react-native';
import {HomeDashboardScreen, getHomeBalanceTone} from './HomeDashboardScreen';

const balanceProps = {
  remainingDataGb: 4.25,
  dataTotalGb: 10,
  pstnMinutesRemaining: 30,
  pstnMinutesTotal: 60,
};

afterEach(async () => {
  await cleanup();
});

it('AC-13.7: shows from seven days before departure, dismisses per mount, and returns next mount', async () => {
  const props = {
    departureDate: '2026-07-20',
    esimStatus: 'downloaded' as const,
    ...balanceProps,
    onActivateEsim: jest.fn(),
    now: new Date('2026-07-15T00:00:00Z'),
  };
  const first = await render(<HomeDashboardScreen {...props} />);
  expect(first.getByTestId('esim-activation-banner')).toBeTruthy();
  fireEvent.press(first.getByTestId('esim-banner-dismiss'));
  await waitFor(() => expect(first.queryByTestId('esim-activation-banner')).toBeNull());
  await first.unmount();
  const reopened = await render(<HomeDashboardScreen {...props} />);
  expect(reopened.getByTestId('esim-activation-banner')).toBeTruthy();
});

it('AC-13.6: activated status hides banner and shows remaining Saudi data', async () => {
  const view = await render(
    <HomeDashboardScreen
      departureDate="2026-07-20"
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
      now={new Date('2026-07-15T00:00:00Z')}
    />,
  );
  expect(view.queryByTestId('esim-activation-banner')).toBeNull();
  expect(view.getByText('Saudi Arabia data — active')).toBeTruthy();
  expect(view.getByText('4.25 GB remaining')).toBeTruthy();
});

it('AC-15.1/15.8: one tap sends immediately with no confirmation dialog', async () => {
  const onCheckIn = jest.fn().mockResolvedValue('sent');
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
      onCheckIn={onCheckIn}
      lastCheckInAt={null}
      queuedCheckIns={0}
    />,
  );

  await act(async () => {
    fireEvent.press(view.getByRole('button', {name: "I'm okay"}));
  });

  await waitFor(() => expect(onCheckIn).toHaveBeenCalledTimes(1));
  expect(view.queryByText(/are you sure/i)).toBeNull();
  expect(view.getByText('Check-in sent')).toBeTruthy();
});

it('AC-15.4: queued check-in and queue count remain visible inline', async () => {
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
      onCheckIn={jest.fn().mockResolvedValue('queued')}
      lastCheckInAt="2026-07-13T08:05:00Z"
      queuedCheckIns={1}
    />,
  );

  await act(async () => {
    fireEvent.press(view.getByRole('button', {name: "I'm okay"}));
  });

  await waitFor(() =>
    expect(view.getByText('Check-in queued, will send when connected')).toBeTruthy(),
  );
  expect(view.getByText('1 event waiting to send')).toBeTruthy();
  expect(view.getByText('1 check-in')).toBeTruthy();
  expect(view.getByText(/Last check-in:/)).toBeTruthy();
});

it('AC-15.9: disables another check-in during the 15-minute window', async () => {
  const onCheckIn = jest.fn().mockResolvedValue('sent');
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
      onCheckIn={onCheckIn}
      lastCheckInAt="2026-07-13T08:05:00Z"
      now={new Date('2026-07-13T08:10:00Z')}
    />,
  );

  fireEvent.press(view.getByRole('button', {name: "I'm okay"}));

  expect(onCheckIn).not.toHaveBeenCalled();
  expect(view.getByText('Check-in available every 15 minutes')).toBeTruthy();
});

it('AC-17.1: persistently renders data and voice balances with progress', async () => {
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
    />,
  );

  expect(view.getByText('4.25 GB remaining')).toBeTruthy();
  expect(view.getByText('30 minutes remaining')).toBeTruthy();
  expect(view.getByTestId('data-balance-progress')).toHaveAccessibilityValue({
    min: 0,
    max: 100,
    now: 42.5,
  });
  expect(view.getByTestId('minutes-balance-progress')).toHaveAccessibilityValue({
    min: 0,
    max: 100,
    now: 50,
  });
});

it.each([
  ['exactly 20% data', 20, 5, 'healthy'],
  ['below 20% data', 19.99, 5, 'warning'],
  ['exactly 5 minutes', 20, 5, 'healthy'],
  ['below 5 minutes', 20, 4.99, 'warning'],
  ['zero data', 0, 30, 'error'],
  ['zero minutes', 80, 0, 'error'],
] as const)('AC-17.3/17.4: %s', (_label, dataPercent, minutes, tone) => {
  expect(getHomeBalanceTone(dataPercent, minutes)).toBe(tone);
});

it('AC-17.3/17.4: renders warning and exhausted banners with exact boundaries', async () => {
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      remainingDataGb={1.999}
      dataTotalGb={10}
      pstnMinutesRemaining={5}
      pstnMinutesTotal={60}
      onActivateEsim={jest.fn()}
    />,
  );
  expect(view.getByTestId('balance-warning-banner')).toBeTruthy();

  await view.rerender(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      remainingDataGb={0}
      dataTotalGb={10}
      pstnMinutesRemaining={5}
      pstnMinutesTotal={60}
      onActivateEsim={jest.fn()}
    />,
  );
  expect(view.getByTestId('balance-error-banner')).toBeTruthy();
});

it('AC-17.5: opens the configured WhatsApp support handoff', async () => {
  const open = jest.spyOn(Linking, 'openURL').mockResolvedValueOnce(undefined);
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
    />,
  );

  fireEvent.press(view.getByRole('button', {name: 'Message support on WhatsApp'}));
  expect(open).toHaveBeenCalledWith(expect.stringContaining('https://wa.me/'));
});

it('AC-24.5: combines pending check-ins and SOS alerts in one Home indicator', async () => {
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      {...balanceProps}
      onActivateEsim={jest.fn()}
      queuedCheckIns={2}
      queuedSOSAlerts={1}
    />,
  );

  expect(view.getByText('3 events waiting to send')).toBeTruthy();
  expect(view.getByText('2 check-ins and 1 SOS alert')).toBeTruthy();
});
