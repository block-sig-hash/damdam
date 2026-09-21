import React from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react-native';
import * as accountClient from '../../api/accountClient';
import { ApiError } from '../../api/http';
import { readSlice, writeSlice } from '../../services/accountCache';
import { press, type } from '../../testing/interact';
import { AccountFlow } from './AccountFlow';

/**
 * US-38 chunk 21 — the account area.
 *
 * Grouped by the mistake each test prevents. Three of those are expensive
 * enough to justify most of the file:
 *
 * **Leaving one customer's data on a shared handset.** Signing out has to clear
 * this account's cache, and every isolation guarantee the API makes is undone if
 * it does not.
 *
 * **Rendering cached content as if it were live.** A receipt list from disk is
 * useful; one that pretends it just checked is how somebody concludes a refund
 * never arrived.
 *
 * **Offering a delete button the server will refuse.** The preflight exists so
 * the screen can say what is in the way, and a disabled button with no
 * explanation is the version that generates support tickets.
 */

jest.mock('../../api/accountClient', () => ({
  ...jest.requireActual('../../api/accountClient'),
  fetchSessions: jest.fn(),
  fetchReceipts: jest.fn(),
  fetchSupportRequests: jest.fn(),
  fetchPreferences: jest.fn(),
  fetchDeletionPreflight: jest.fn(),
  revokeSession: jest.fn(),
  revokeAllSessions: jest.fn(),
  setPreference: jest.fn(),
  openSupportRequest: jest.fn(),
  requestExport: jest.fn(),
  deleteAccount: jest.fn(),
}));

const mocked = accountClient as jest.Mocked<typeof accountClient>;

const SESSION = {
  session_id: 'session-1',
  platform: 'android' as const,
  device_label: 'Pixel 7',
  app_version: '1.0.0',
  last_seen_city: 'Lagos',
  last_seen_country: 'NG',
  last_seen_at: '2026-09-12T10:00:00Z',
  revoked_at: null,
  is_current: true,
};

const RECEIPT = {
  order_id: 'order-1',
  reference: 'ORD-ABCD1234',
  placed_at: '2026-09-01T09:00:00Z',
  currency: 'NGN',
  total_amount: '5000.000000',
  payment_state: 'paid',
  lines: [
    {
      description: 'Nigeria 5GB',
      quantity: 1,
      unit_amount: '5000.000000',
      total_amount: '5000.000000',
    },
  ],
  organization_id: null,
};

async function renderFlow(
  overrides: Partial<React.ComponentProps<typeof AccountFlow>> = {},
) {
  // `act`-wrapped, matching chunk 19's purchase suite and chunk 20's line
  // suite: the mount effect resolves across several microtasks, and an
  // unwrapped render leaves those updates outside React's act scope — pages of
  // console noise around a test that otherwise passes.
  await act(async () => {
    render(
    <AccountFlow
      accessToken="token"
      userId="user-a"
      displayName="Holder Person"
      phoneNumber="+2348010000001"
      email="holder@example.test"
      onAccountDeleted={overrides.onAccountDeleted ?? jest.fn()}
      onSignedOutEverywhere={overrides.onSignedOutEverywhere ?? jest.fn()}
      {...overrides}
    />,
    );
  });
}

function happyPath() {
  mocked.fetchSessions.mockResolvedValue({ sessions: [SESSION] });
  mocked.fetchReceipts.mockResolvedValue({ receipts: [RECEIPT] });
  mocked.fetchSupportRequests.mockResolvedValue({ requests: [] });
  mocked.fetchPreferences.mockResolvedValue({ preferences: [] });
}

describe('AccountFlow', () => {
  beforeEach(async () => {
    jest.clearAllMocks();
    mocked.deleteAccount.mockResolvedValue({
      status: 'pending_deletion',
      deletion_requested_at: '2026-09-12T10:00:00Z',
    });
    await AsyncStorage.clear();
  });

  afterEach(cleanup);

  describe('what it shows', () => {
    it('counts the devices and receipts on the account', async () => {
      happyPath();

      await renderFlow();

      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      expect(screen.getByTestId('account-device-count')).toHaveTextContent('1');
      expect(screen.getByTestId('account-receipt-count')).toHaveTextContent('1');
    });

    it('does not count a revoked device as signed in', async () => {
      mocked.fetchSessions.mockResolvedValue({
        sessions: [{ ...SESSION, revoked_at: '2026-09-12T11:00:00Z' }],
      });
      mocked.fetchReceipts.mockResolvedValue({ receipts: [] });
      mocked.fetchSupportRequests.mockResolvedValue({ requests: [] });
      mocked.fetchPreferences.mockResolvedValue({ preferences: [] });

      await renderFlow();

      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      expect(screen.getByTestId('account-device-count')).toHaveTextContent('0');
    });
  });

  describe('offline', () => {
    it('falls back to the cached receipts and says they are cached', async () => {
      await writeSlice('user-a', 'receipts', [RECEIPT], '2026-09-11T08:00:00Z');
      mocked.fetchSessions.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );
      mocked.fetchReceipts.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );
      mocked.fetchSupportRequests.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );
      mocked.fetchPreferences.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );

      await renderFlow();

      await waitFor(() => expect(screen.getByTestId('account-offline')).toBeTruthy());
      expect(screen.getByTestId('account-observed-at')).toHaveTextContent(
        '2026-09-11T08:00:00Z',
      );
      expect(screen.getByTestId('account-receipt-count')).toHaveTextContent('1');
    });

    it('shows an error rather than an empty account when nothing is cached', async () => {
      mocked.fetchSessions.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );
      mocked.fetchReceipts.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );
      mocked.fetchSupportRequests.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );
      mocked.fetchPreferences.mockRejectedValue(
        new ApiError('network_error', 'offline', 0),
      );

      await renderFlow();

      await waitFor(() => expect(screen.getByTestId('account-error')).toBeTruthy());
    });

    it('writes receipts to disk after a successful load', async () => {
      happyPath();

      await renderFlow();

      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await waitFor(async () =>
        expect(await readSlice('user-a', 'receipts')).not.toBeNull(),
      );
    });
  });

  describe('devices', () => {
    it('signs one device out and reloads', async () => {
      happyPath();
      mocked.revokeSession.mockResolvedValue(undefined);

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-devices');
      await waitFor(() => expect(screen.getByTestId('devices-screen')).toBeTruthy());
      await press('revoke-session-1');

      await waitFor(() =>
        expect(mocked.revokeSession).toHaveBeenCalledWith('token', 'session-1'),
      );
    });

    it('asks before signing every device out', async () => {
      happyPath();

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-devices');
      await press('revoke-all');

      expect(screen.getByTestId('revoke-all-confirm')).toBeTruthy();
      expect(mocked.revokeAllSessions).not.toHaveBeenCalled();
    });

    it('clears this account cache when every device is signed out', async () => {
      happyPath();
      mocked.revokeAllSessions.mockResolvedValue({ revoked: 1 });
      await writeSlice('user-a', 'receipts', [RECEIPT], '2026-09-11T08:00:00Z');
      const onSignedOutEverywhere = jest.fn();

      await renderFlow({ onSignedOutEverywhere });
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-devices');
      await press('revoke-all');
      await press('revoke-all-including-this');

      await waitFor(() => expect(onSignedOutEverywhere).toHaveBeenCalled());
      expect(await readSlice('user-a', 'receipts')).toBeNull();
    });
  });

  describe('deletion', () => {
    it('offers deletion only after the preflight says it may', async () => {
      happyPath();
      mocked.fetchDeletionPreflight.mockResolvedValue({
        may_delete: true,
        blockers: [],
      });

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-privacy');

      await waitFor(() => expect(screen.getByTestId('delete-start')).toBeTruthy());
    });

    it('explains what is in the way instead of offering the button', async () => {
      happyPath();
      mocked.fetchDeletionPreflight.mockResolvedValue({
        may_delete: false,
        blockers: [
          {
            kind: 'others_depend_on_this_account',
            code: 'organization_has_other_members',
            amount: null,
            currency: null,
          },
        ],
      });

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-privacy');

      await waitFor(() => expect(screen.getByTestId('deletion-blocked')).toBeTruthy());
      expect(
        screen.getByTestId('blocker-organization_has_other_members'),
      ).toBeTruthy();
      expect(screen.queryByTestId('delete-start')).toBeNull();
    });

    it('names the amount when a refund is what is in the way', async () => {
      happyPath();
      mocked.fetchDeletionPreflight.mockResolvedValue({
        may_delete: false,
        blockers: [
          {
            kind: 'unsettled_money',
            code: 'refund_in_progress',
            amount: '4000.00',
            currency: 'NGN',
          },
        ],
      });

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-privacy');

      await waitFor(() =>
        expect(screen.getByTestId('blocker-refund_in_progress')).toHaveTextContent(
          'A refund of 4000.00 NGN is still going through.',
        ),
      );
    });

    it('falls back to a general sentence for a code it does not know', async () => {
      happyPath();
      mocked.fetchDeletionPreflight.mockResolvedValue({
        may_delete: false,
        blockers: [
          {
            kind: 'active_liability',
            code: 'some_future_reason',
            amount: null,
            currency: null,
          },
        ],
      });

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-privacy');

      await waitFor(() =>
        expect(screen.getByTestId('blocker-some_future_reason')).toHaveTextContent(
          'Something on your account is still in progress.',
        ),
      );
    });

    it('clears this account cache before leaving', async () => {
      happyPath();
      mocked.fetchDeletionPreflight.mockResolvedValue({
        may_delete: true,
        blockers: [],
      });
      await writeSlice('user-a', 'receipts', [RECEIPT], '2026-09-11T08:00:00Z');
      const onAccountDeleted = jest.fn();

      await renderFlow({ onAccountDeleted });
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-privacy');
      await waitFor(() => expect(screen.getByTestId('delete-start')).toBeTruthy());
      await press('delete-start');
      await press('delete-confirm');

      await waitFor(() => expect(onAccountDeleted).toHaveBeenCalled());
      expect(mocked.deleteAccount).toHaveBeenCalledWith('token');
      expect(await readSlice('user-a', 'receipts')).toBeNull();
    });

    it('keeps the local session when server deletion is refused', async () => {
      happyPath();
      mocked.fetchDeletionPreflight.mockResolvedValue({ may_delete: true, blockers: [] });
      mocked.deleteAccount.mockRejectedValue(
        new ApiError('account_deletion_blocked', 'Deletion blocked', 409),
      );
      await writeSlice('user-a', 'receipts', [RECEIPT], '2026-09-11T08:00:00Z');
      const onAccountDeleted = jest.fn();

      await renderFlow({ onAccountDeleted });
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-privacy');
      await waitFor(() => expect(screen.getByTestId('delete-start')).toBeTruthy());
      await press('delete-start');
      await press('delete-confirm');

      await waitFor(() =>
        expect(screen.getByText('Deletion blocked')).toBeTruthy(),
      );
      expect(onAccountDeleted).not.toHaveBeenCalled();
      expect(await readSlice('user-a', 'receipts')).not.toBeNull();
    });
  });

  describe('notification preferences', () => {
    it('shows a switch on when nobody has decided', async () => {
      happyPath();

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-notifications');

      expect(screen.getByTestId('pref-low_balance-push').props.value).toBe(true);
    });

    it('shows a switch off when somebody decided against it', async () => {
      mocked.fetchSessions.mockResolvedValue({ sessions: [SESSION] });
      mocked.fetchReceipts.mockResolvedValue({ receipts: [] });
      mocked.fetchSupportRequests.mockResolvedValue({ requests: [] });
      mocked.fetchPreferences.mockResolvedValue({
        preferences: [
          { category: 'low_balance', channel: 'push', enabled: false },
        ],
      });

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-notifications');

      expect(screen.getByTestId('pref-low_balance-push').props.value).toBe(false);
    });
  });

  describe('support', () => {
    it('sends a request and shows the reference to quote', async () => {
      happyPath();
      mocked.openSupportRequest.mockResolvedValue({
        request_id: 'request-1',
        reference: 'S-ABCD2345',
        category: 'billing',
        state: 'open',
        subject: 'Charged twice',
        created_at: '2026-09-12T12:00:00Z',
        order_id: null,
        entitlement_id: null,
        subject_summary: null,
      });

      await renderFlow();
      await waitFor(() => expect(screen.getByTestId('account-screen')).toBeTruthy());
      await press('open-support');

      await type('support-subject', 'Charged twice');
      await type('support-body', 'I think I paid twice.');
      await press('support-submit');

      await waitFor(() =>
        expect(screen.getByTestId('support-sent')).toHaveTextContent(
          "We've got it. Your reference is S-ABCD2345.",
        ),
      );
    });
  });
});
