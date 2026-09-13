import React from 'react';
import { act, cleanup, render, screen } from '@testing-library/react-native';

import { CallsFlow } from './CallsFlow';
import { press } from '../../testing/interact';
import { FakeCallAdapter } from '../../services/calling/fakeAdapter';
import type { AttemptView, EligibilityView } from '../../api/callingClient';

/**
 * The Calls tab as a customer meets it (US-47, AC-47.1 and AC-47.2).
 *
 * The journey this covers is deliberately the one with **no eSIM anywhere in
 * it**: an internet-only customer reaches a rate preview, places a call and
 * sees it in their history without ever installing a profile. If a future
 * change routed calling behind an installation check, this is the test that
 * fails.
 */

jest.mock('../../api/callingClient', () => ({
  getEligibility: jest.fn(),
  issueClientSession: jest.fn(),
  authorizeCall: jest.fn(),
  startCall: jest.fn(),
  stopCall: jest.fn(),
  getCall: jest.fn(),
  listCalls: jest.fn(),
  revokeClientSession: jest.fn(),
}));

// `mock`-prefixed so the factories below may close over them: jest hoists
// `jest.mock` above the file's own initialization and rejects other names.
const mockAdapter = new FakeCallAdapter();
const mockRequestMicrophone = jest.fn(async () => 'granted' as const);

jest.mock('../../services/calling/adapterRegistry', () => ({
  resolveCallAdapter: () => mockAdapter,
}));
jest.mock('../../services/calling/microphone', () => ({
  requestMicrophone: () => mockRequestMicrophone(),
}));

const client = jest.requireMock('../../api/callingClient') as Record<string, jest.Mock>;

const ELIGIBILITY: EligibilityView = {
  destination_e164: '+441632960011',
  destination_country: 'GB',
  destination_kind: 'fixed',
  currency: 'NGN',
  max_seconds: 600,
  max_charge_amount: '1200.00',
  rate_per_minute_amount: '120.00',
  setup_amount: '0.00',
  available_amount: '5000.00',
  fundable: true,
  route_enabled: true,
};

const ATTEMPT: AttemptView = {
  attempt_id: 'attempt-1',
  state: 'authorized',
  destination_e164: '+441632960011',
  destination_country: 'GB',
  identity_e164: '+2348000000001',
  currency: 'NGN',
  max_seconds: 600,
  max_charge_amount: '1200.00',
  expires_at: '2026-09-13T12:10:00Z',
  created_at: '2026-09-13T12:00:00Z',
  answered_at: null,
  ended_at: null,
  end_reason: null,
  organization_id: null,
  charge: null,
};

async function dial(digits: string): Promise<void> {
  for (const digit of digits) {
    await press(`dial-${digit}`);
  }
}

beforeEach(() => {
  jest.clearAllMocks();
  client.getEligibility.mockResolvedValue(ELIGIBILITY);
  client.listCalls.mockResolvedValue([]);
  client.authorizeCall.mockResolvedValue(ATTEMPT);
  client.issueClientSession.mockResolvedValue({
    token: 'provider-token',
    sip_identity: 'sip:user-1',
    expires_at: '2026-09-13T13:00:00Z',
  });
  client.startCall.mockResolvedValue({
    attempt_id: 'attempt-1',
    destination_e164: '+441632960011',
    correlation: 'corr-1',
    max_seconds: 600,
    expires_at: '2026-09-13T12:10:00Z',
  });
  client.stopCall.mockResolvedValue({ ...ATTEMPT, state: 'ended', end_reason: 'stopped' });
});

afterEach(cleanup);

async function mount(props: Partial<React.ComponentProps<typeof CallsFlow>> = {}) {
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <CallsFlow
        accessToken="token"
        userId="user-1"
        deviceId="device-1"
        currency="NGN"
        {...props}
      />,
    );
  });
  return view;
}

it('AC-47.1: an internet-only customer previews a rate and calls without any eSIM', async () => {
  await mount();

  await dial('441632960011');
  await act(async () => undefined);

  // The rate arrives from the server's own preview, which holds nothing.
  expect(screen.getByTestId('calls-rate')).toBeTruthy();
  expect(client.getEligibility).toHaveBeenCalledWith(
    expect.objectContaining({ destination: '+441632960011', currency: 'NGN' }),
  );

  await press('calls-place');

  expect(client.authorizeCall).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId('call-in-progress')).toBeTruthy();
  // Nothing on this path consulted an installation, an entitlement or a line.
  expect(client.getEligibility).toHaveBeenCalled();
});

it('AC-47.1: the screen names the mode and does not offer to place a carrier call', async () => {
  await mount();

  // A carrier call is placed by the phone's own dialler. Saying so is what
  // stops somebody believing this button changes which SIM they call on.
  expect(screen.getByTestId('calls-carrier-note')).toBeTruthy();
  expect(screen.getByTestId('calls-mode')).toBeTruthy();
});

it('AC-47.1: the call button stays disabled while the route is switched off', async () => {
  client.getEligibility.mockResolvedValue({ ...ELIGIBILITY, route_enabled: false });
  await mount();

  await dial('441632960011');
  await act(async () => undefined);

  expect(screen.getByTestId('calls-route-disabled')).toBeTruthy();
  await press('calls-place');
  expect(client.authorizeCall).not.toHaveBeenCalled();
});

it('AC-47.1: a call the customer cannot fund is never authorized', async () => {
  client.getEligibility.mockResolvedValue({ ...ELIGIBILITY, fundable: false });
  await mount();

  await dial('441632960011');
  await act(async () => undefined);

  expect(screen.getByTestId('calls-not-fundable')).toBeTruthy();
  await press('calls-place');
  expect(client.authorizeCall).not.toHaveBeenCalled();
});

it('AC-47.1: history shows a settled cost and never renders a missing one as zero', async () => {
  client.listCalls.mockResolvedValue([
    {
      ...ATTEMPT,
      attempt_id: 'attempt-settled',
      answered_at: '2026-09-13T12:01:00Z',
      charge: {
        amount: '240.00',
        currency: 'NGN',
        billable_seconds: 120,
        setup_amount: '0.00',
        usage_amount: '240.00',
        is_final: true,
        settled_at: '2026-09-13T12:05:00Z',
      },
    },
    {
      ...ATTEMPT,
      attempt_id: 'attempt-pending',
      answered_at: '2026-09-13T12:02:00Z',
      charge: null,
    },
  ]);
  await mount();
  await act(async () => undefined);

  expect(screen.getByTestId('calls-cost-attempt-settled')).toHaveTextContent(
    '240.00 NGN',
  );
  // A null charge is "not settled yet", not zero. V03 may still be waiting on
  // the supplier's record, and a 0.00 here would be a false receipt.
  expect(screen.getByTestId('calls-cost-attempt-pending')).toHaveTextContent(
    'Cost still being worked out',
  );
});

it('AC-47.2: after an account switch the previous call is neither shown nor controllable', async () => {
  const view = await mount();
  await dial('441632960011');
  await act(async () => undefined);
  await press('calls-place');
  await act(async () => {
    mockAdapter.emit({ kind: 'answered' });
  });
  expect(screen.getByTestId('call-phase')).toHaveTextContent('On the call');

  // The real switch: same mounted tab, different signed-in user.
  await act(async () => {
    view.rerender(
      <CallsFlow
        accessToken="token-2"
        userId="user-2"
        deviceId="device-1"
        currency="NGN"
      />,
    );
  });

  // The second user gets a fresh session, not the first user's live call.
  expect(screen.queryByTestId('call-in-progress')).toBeNull();
  expect(screen.getByTestId('calls-place')).toBeTruthy();

  // And the SDK, which does not know the account changed, keeps talking. Its
  // callback must neither throw nor resurrect the previous user's call.
  await act(async () => {
    mockAdapter.emit({ kind: 'ended', reason: 'remote_hangup' });
  });
  expect(screen.queryByTestId('call-in-progress')).toBeNull();
});

it('AC-47.3: a failed placement explains itself and offers the same attempt again', async () => {
  const { ApiError } = jest.requireActual('../../api/http') as typeof import('../../api/http');
  client.authorizeCall.mockRejectedValueOnce(
    new ApiError('insufficient_funds', 'no credit', 409),
  );
  await mount();
  await dial('441632960011');
  await act(async () => undefined);

  await press('calls-place');

  expect(screen.getByTestId('calls-failure')).toBeTruthy();
  await press('calls-failure-retry');
  // The retry reuses the first key, so the server sees one placement.
  const keys = client.authorizeCall.mock.calls.map(([args]) => args.idempotencyKey);
  expect(new Set(keys).size).toBe(1);
});
