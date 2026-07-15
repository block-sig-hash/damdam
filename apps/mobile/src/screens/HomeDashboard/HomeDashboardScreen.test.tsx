import React from 'react';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react-native';
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
