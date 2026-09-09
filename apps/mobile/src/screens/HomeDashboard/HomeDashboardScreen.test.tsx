import React from 'react';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react-native';
import {Linking} from 'react-native';
import {
  getBalanceProgressTone,
  getHomeBalanceTone,
  HomeDashboardScreen,
} from './HomeDashboardScreen';

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

it.each([
  ['data at 20%', 'data', 20, 20, 'healthy'],
  ['data below 20%', 'data', 19.99, 20, 'warning'],
  ['data at zero', 'data', 0, 0, 'error'],
  ['minutes at 5', 'minutes', 8, 5, 'healthy'],
  ['minutes below 5', 'minutes', 80, 4.99, 'warning'],
  ['minutes at zero', 'minutes', 80, 0, 'error'],
] as const)(
  'AC-17.3/17.4 progress color: %s',
  (_label, kind, percent, remaining, tone) => {
    expect(getBalanceProgressTone(kind, percent, remaining)).toBe(tone);
  },
);

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

