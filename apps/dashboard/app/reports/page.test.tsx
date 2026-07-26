import {cleanup, fireEvent, render, screen, waitFor} from '@/test-utils';
import {afterEach, expect, it, vi} from 'vitest';

const {default: ReportsPage} = await import('./page');

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });

function stubDownload() {
  vi.stubGlobal('URL', {
    ...URL,
    createObjectURL: vi.fn(() => 'blob:mock'),
    revokeObjectURL: vi.fn(),
  });
}

it('AC-20.3: loads the operator\'s manifests into the selector', async () => {
  localStorage.setItem('hto_access_token', 'operator-token');
  const fetchMock = vi.fn().mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      manifests: [
        {id: 'm-1', name: 'Flight NAF203', status: 'provisioned', valid_rows: 42, created_at: '2026-06-01T00:00:00Z'},
      ],
    }),
  });
  vi.stubGlobal('fetch', fetchMock);

  render(<ReportsPage />);

  expect(await screen.findByRole('option', {name: 'Flight NAF203'})).toBeInTheDocument();
  expect(screen.getByRole('option', {name: 'All manifests'})).toBeInTheDocument();
});

it('AC-20.1/20.3: downloading passes the selected manifest and date range as query params', async () => {
  localStorage.setItem('hto_access_token', 'operator-token');
  stubDownload();
  const blob = new Blob(['name,phone\n'], {type: 'text/csv'});
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ok: true, json: async () => ({manifests: []})})
    .mockResolvedValueOnce({ok: true, blob: async () => blob});
  vi.stubGlobal('fetch', fetchMock);

  render(<ReportsPage />);
  await screen.findByRole('button', {name: 'Download CSV'});

  fireEvent.change(screen.getByLabelText('From'), {target: {value: '2026-06-01'}});
  fireEvent.change(screen.getByLabelText('To'), {target: {value: '2026-06-30'}});
  fireEvent.click(screen.getByRole('button', {name: 'Download CSV'}));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  const requestedUrl = fetchMock.mock.calls[1][0] as string;
  expect(requestedUrl).toContain('/hto/reports/provisioning.csv');
  expect(requestedUrl).toContain('date_from=2026-06-01');
  expect(requestedUrl).toContain('date_to=2026-06-30');
  expect(requestedUrl).not.toContain('manifest_id=');
});

it('AC-20.4: shows a generating state with the 30s expectation while the request is in flight', async () => {
  localStorage.setItem('hto_access_token', 'operator-token');
  stubDownload();
  let resolveDownload: (value: {ok: boolean; blob: () => Promise<Blob>}) => void = () => {};
  const downloadPromise = new Promise(resolve => { resolveDownload = resolve; });
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ok: true, json: async () => ({manifests: []})})
    .mockReturnValueOnce(downloadPromise);
  vi.stubGlobal('fetch', fetchMock);

  render(<ReportsPage />);
  const button = await screen.findByRole('button', {name: 'Download CSV'});
  fireEvent.click(button);

  expect(await screen.findByRole('button', {name: 'Generating…'})).toBeDisabled();
  expect(screen.getByText(/up to 30 seconds/)).toBeInTheDocument();

  resolveDownload({ok: true, blob: async () => new Blob(['x'])});
  await waitFor(() => expect(screen.getByRole('button', {name: 'Download CSV'})).not.toBeDisabled());
});

it('shows an inline error and re-enables the button if generation fails', async () => {
  localStorage.setItem('hto_access_token', 'operator-token');
  stubDownload();
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ok: true, json: async () => ({manifests: []})})
    .mockResolvedValueOnce({ok: false, json: async () => ({message: 'Sign in to continue.'})});
  vi.stubGlobal('fetch', fetchMock);

  render(<ReportsPage />);
  fireEvent.click(await screen.findByRole('button', {name: 'Download CSV'}));

  expect(await screen.findByRole('alert')).toHaveTextContent('Sign in to continue.');
  expect(screen.getByRole('button', {name: 'Download CSV'})).not.toBeDisabled();
});
