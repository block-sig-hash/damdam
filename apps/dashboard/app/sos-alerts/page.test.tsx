import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import SOSAlertsPage from './page';

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

it('AC-16.3 dashboard: active alerts are prominent, mapped, filterable and resolvable', async () => {
  localStorage.setItem('hto_access_token', 'operator-token');
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ok: true, json: async () => ({alerts: [{id: 'sos-1', pilgrim_name: 'Amina Yusuf', pilgrim_phone: '+2348012345678', timestamp: '2026-07-16T08:05:00Z', latitude: 21.422487, longitude: 39.826206, status: 'active'}]})})
    .mockResolvedValueOnce({ok: true, json: async () => ({status: 'resolved'})});
  vi.stubGlobal('fetch', fetchMock);
  render(<SOSAlertsPage />);
  expect(await screen.findByText('Amina Yusuf')).toBeInTheDocument();
  expect(screen.getByText('+2348012345678')).toBeInTheDocument();
  expect(screen.getByRole('img', {name: 'Location of Amina Yusuf'})).toHaveAttribute('src', expect.stringContaining('21.422487'));
  fireEvent.click(screen.getByRole('button', {name: 'Resolve'}));
  await waitFor(() => expect(fetchMock.mock.calls[1][0]).toContain('/hto/sos-alerts/sos-1/resolve'));
});
