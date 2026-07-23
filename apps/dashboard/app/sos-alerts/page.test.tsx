import {cleanup, fireEvent, render, screen, waitFor} from '@/test-utils';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';

const enableSOSPushAlertsMock = vi.fn(async () => 'subscribed' as const);
vi.mock('../../lib/push', () => ({
  enableSOSPushAlerts: enableSOSPushAlertsMock,
  listenForForegroundSOSPush: vi.fn(() => () => undefined),
}));

const {default: SOSAlertsPage} = await import('./page');

beforeEach(() => enableSOSPushAlertsMock.mockClear());
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

it('AC-19.1: the push banner never prompts on load, only on click, and hides once acted on', async () => {
  const notificationStub: {permission: NotificationPermission; requestPermission: () => void} = {
    permission: 'default',
    requestPermission: vi.fn(),
  };
  // enableSOSPushAlerts is mocked directly (its own real permission-request
  // logic is covered by lib/push.test.ts), but the page re-reads
  // Notification.permission afterward to decide whether to hide the
  // banner, so the stub must reflect what a real grant would have done.
  enableSOSPushAlertsMock.mockImplementation(async () => {
    notificationStub.permission = 'granted';
    return 'subscribed';
  });
  vi.stubGlobal('Notification', notificationStub);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, json: async () => ({alerts: []})}));
  render(<SOSAlertsPage />);

  const button = await screen.findByRole('button', {name: 'Enable browser alerts'});
  expect(enableSOSPushAlertsMock).not.toHaveBeenCalled();

  fireEvent.click(button);

  await waitFor(() => expect(enableSOSPushAlertsMock).toHaveBeenCalledTimes(1));
  await waitFor(() =>
    expect(screen.queryByRole('button', {name: 'Enable browser alerts'})).not.toBeInTheDocument(),
  );
});

it('AC-19.1: shows nothing push-related when the browser is unsupported', async () => {
  vi.stubGlobal('Notification', undefined);
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, json: async () => ({alerts: []})}));
  render(<SOSAlertsPage />);

  await screen.findByText('No active SOS alerts.');
  expect(screen.queryByRole('button', {name: 'Enable browser alerts'})).not.toBeInTheDocument();
});
