import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import {
  getCliStatus,
  reportCliLostSim,
  revokeCli,
  type VerifiedCallerIdentity,
} from '../../api/cliClient';
import { CliManageScreen } from './CliManageScreen';

jest.mock('../../api/cliClient', () => {
  const actual = jest.requireActual('../../api/cliClient');
  return {
    ...actual,
    getCliStatus: jest.fn(),
    revokeCli: jest.fn(),
    reportCliLostSim: jest.fn(),
  };
});

afterEach(async () => cleanup());

const mockStatus = getCliStatus as jest.MockedFunction<typeof getCliStatus>;
const mockRevoke = revokeCli as jest.MockedFunction<typeof revokeCli>;
const mockLostSim = reportCliLostSim as jest.MockedFunction<typeof reportCliLostSim>;

const ACTIVE: VerifiedCallerIdentity = {
  id: 'identity-1',
  phone_number: '+2348031234567',
  status: 'active',
  phone_verification_status: 'verified',
  consent_version: 'v1',
  consent_at: '2026-07-25T00:00:00Z',
  created_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:00:00Z',
};

beforeEach(() => {
  mockStatus.mockReset();
  mockRevoke.mockReset();
  mockLostSim.mockReset();
});

describe('CliManageScreen', () => {
  it('prompts to verify a number when there is no identity yet', async () => {
    mockStatus.mockResolvedValue(null);
    const onVerifyNumber = jest.fn();
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={onVerifyNumber}
        onResumeConfirm={jest.fn()}
        onResumeConsent={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByTestId('cli-manage-verify')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('cli-manage-verify'));
    expect(onVerifyNumber).toHaveBeenCalledTimes(1);
  });

  it('shows the active verified number with revoke/lost-SIM actions', async () => {
    mockStatus.mockResolvedValue(ACTIVE);
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={jest.fn()}
        onResumeConfirm={jest.fn()}
        onResumeConsent={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByTestId('cli-manage-active-number')).toBeTruthy());
    expect(screen.getByText('0803 123 4567')).toBeTruthy();
    expect(screen.getByTestId('cli-manage-revoke')).toBeTruthy();
    expect(screen.getByTestId('cli-manage-lost-sim')).toBeTruthy();
  });

  it('AC-14.11: revoking requires an inline confirmation before calling the API', async () => {
    mockStatus.mockResolvedValue(ACTIVE);
    mockRevoke.mockResolvedValue(undefined);
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={jest.fn()}
        onResumeConfirm={jest.fn()}
        onResumeConsent={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('cli-manage-revoke')).toBeTruthy());

    await fireEvent.press(screen.getByTestId('cli-manage-revoke'));
    expect(mockRevoke).not.toHaveBeenCalled();
    expect(screen.getByTestId('cli-manage-revoke-confirm')).toBeTruthy();

    mockStatus.mockResolvedValue(null);
    await fireEvent.press(screen.getByTestId('cli-manage-revoke-confirm'));

    expect(mockRevoke).toHaveBeenCalledWith('token');
    await waitFor(() => expect(screen.getByTestId('cli-manage-verify')).toBeTruthy());
  });

  it('cancelling the revoke confirmation does not call the API', async () => {
    mockStatus.mockResolvedValue(ACTIVE);
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={jest.fn()}
        onResumeConfirm={jest.fn()}
        onResumeConsent={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('cli-manage-revoke')).toBeTruthy());

    await fireEvent.press(screen.getByTestId('cli-manage-revoke'));
    await fireEvent.press(screen.getByTestId('cli-manage-revoke-cancel'));

    expect(mockRevoke).not.toHaveBeenCalled();
    expect(screen.getByTestId('cli-manage-revoke')).toBeTruthy();
  });

  it('reports a lost SIM after inline confirmation', async () => {
    mockStatus.mockResolvedValue(ACTIVE);
    mockLostSim.mockResolvedValue(undefined);
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={jest.fn()}
        onResumeConfirm={jest.fn()}
        onResumeConsent={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByTestId('cli-manage-lost-sim')).toBeTruthy());

    await fireEvent.press(screen.getByTestId('cli-manage-lost-sim'));
    mockStatus.mockResolvedValue(null);
    await fireEvent.press(screen.getByTestId('cli-manage-lost-sim-confirm'));

    expect(mockLostSim).toHaveBeenCalledWith('token');
  });

  it('resumes an in-progress verification at the confirm step', async () => {
    const pending: VerifiedCallerIdentity = {
      ...ACTIVE,
      status: 'phone_verification_pending',
    };
    mockStatus.mockResolvedValue(pending);
    const onResumeConfirm = jest.fn();
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={jest.fn()}
        onResumeConfirm={onResumeConfirm}
        onResumeConsent={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByTestId('cli-manage-continue-confirm')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('cli-manage-continue-confirm'));
    expect(onResumeConfirm).toHaveBeenCalledWith(pending);
  });

  it('resumes an in-progress verification at the consent step', async () => {
    const consentRequired: VerifiedCallerIdentity = { ...ACTIVE, status: 'consent_required' };
    mockStatus.mockResolvedValue(consentRequired);
    const onResumeConsent = jest.fn();
    await render(
      <CliManageScreen
        accessToken="token"
        onVerifyNumber={jest.fn()}
        onResumeConfirm={jest.fn()}
        onResumeConsent={onResumeConsent}
      />,
    );

    await waitFor(() => expect(screen.getByTestId('cli-manage-continue-consent')).toBeTruthy());
    await fireEvent.press(screen.getByTestId('cli-manage-continue-consent'));
    expect(onResumeConsent).toHaveBeenCalledWith(consentRequired);
  });
});
