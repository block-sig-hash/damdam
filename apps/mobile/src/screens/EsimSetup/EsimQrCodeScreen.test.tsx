import React from 'react';
import { act, cleanup, render, renderHook, waitFor } from '@testing-library/react-native';
import { issueEsim, markEsimDownloaded } from '../../api/esimClient';
import { downloadEsimProfile } from '../../services/esimDownload';
import { EsimQrCodeScreen } from './EsimQrCodeScreen';
import { useEsimProfile } from './useEsimProfile';

jest.mock('../../api/esimClient', () => {
  const actual = jest.requireActual('../../api/esimClient');
  return { ...actual, issueEsim: jest.fn(), markEsimDownloaded: jest.fn() };
});
jest.mock('../../services/esimDownload', () => ({ downloadEsimProfile: jest.fn() }));

const mockIssue = issueEsim as jest.MockedFunction<typeof issueEsim>;
const mockMark = markEsimDownloaded as jest.MockedFunction<typeof markEsimDownloaded>;
const mockDownload = downloadEsimProfile as jest.MockedFunction<typeof downloadEsimProfile>;
const profile = {
  esim_profile_id: 'profile-1',
  iccid: '8944501234567890123456',
  activation_code_lpa: 'LPA:1$server$match',
  qr_code_url: 'https://cdn.example/qr.png',
  status: 'issued' as const,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockIssue.mockResolvedValue(profile);
  mockDownload.mockResolvedValue('invoked');
  mockMark.mockResolvedValue({ status: 'downloaded' });
});

afterEach(async () => {
  await cleanup();
});

it('AC-11.1/11.3: shows timing guidance, QR, ICCID, and activation fallback', async () => {
  const view = await render(<EsimQrCodeScreen accessToken="token" packageId="package-1" />);
  expect(await view.findByTestId('esim-qr-image')).toBeTruthy();
  expect(view.getByText(/2–7 days before/)).toBeTruthy();
  expect(view.getByText(profile.iccid)).toBeTruthy();
  expect(view.getByText(profile.activation_code_lpa)).toBeTruthy();
  expect(view.getByTestId('esim-save-qr')).toBeTruthy();
});

it('AC-11.2/11.4: disables double taps while invoking download and marks it once', async () => {
  let resolveDownload!: (value: 'invoked') => void;
  mockDownload.mockReturnValue(new Promise(resolve => { resolveDownload = resolve; }));
  const hook = await renderHook(() => useEsimProfile('token', 'package-1'));
  await waitFor(() => expect(hook.result.current.phase).toBe('ready'));

  await act(async () => {
    const first = hook.result.current.download();
    const second = hook.result.current.download();
    expect(mockDownload).toHaveBeenCalledTimes(1);
    resolveDownload('invoked');
    await Promise.all([first, second]);
  });
  await waitFor(() => expect(mockMark).toHaveBeenCalledTimes(1));
  expect(hook.result.current.phase).toBe('downloaded');
});

it('AC-11.5: explains that a failed issue is queued for automatic retry', async () => {
  const { EsimApiError } = jest.requireMock('../../api/esimClient') as {
    EsimApiError: new (message: string, code: string) => Error;
  };
  mockIssue.mockRejectedValue(new EsimApiError('queued', 'aggregator_unavailable'));
  const view = await render(<EsimQrCodeScreen accessToken="token" packageId="package-1" />);
  expect(await view.findByTestId('esim-profile-queued')).toBeTruthy();
  expect(view.getByText(/queued and will retry automatically/)).toBeTruthy();
});
