import React from 'react';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react-native';
import { HomeDashboardScreen } from './HomeDashboardScreen';

afterEach(async () => {
  await cleanup();
});

it('AC-13.7: shows from seven days before departure, dismisses per mount, and returns next mount', async () => {
  const props = {
    departureDate: '2026-07-20',
    esimStatus: 'downloaded' as const,
    remainingDataGb: 0,
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
      remainingDataGb={4.25}
      onActivateEsim={jest.fn()}
      now={new Date('2026-07-15T00:00:00Z')}
    />,
  );
  expect(view.queryByTestId('esim-activation-banner')).toBeNull();
  expect(view.getByText('Saudi Arabia data — active')).toBeTruthy();
  expect(view.getByText('4.25 GB')).toBeTruthy();
});

it('AC-15.1/15.8: one tap sends immediately with no confirmation dialog', async () => {
  const onCheckIn = jest.fn().mockResolvedValue('sent');
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      remainingDataGb={4.25}
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
      remainingDataGb={4.25}
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
  expect(view.getByText('1 check-in waiting to send')).toBeTruthy();
  expect(view.getByText(/Last check-in:/)).toBeTruthy();
});

it('AC-15.9: disables another check-in during the 15-minute window', async () => {
  const onCheckIn = jest.fn().mockResolvedValue('sent');
  const view = await render(
    <HomeDashboardScreen
      departureDate={null}
      esimStatus="activated"
      remainingDataGb={4.25}
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
