import type { AttemptView, StartInstruction } from '../../api/callingClient';
import { ApiError } from '../../api/http';
import { CallSessionController } from './callSession';
import { UnavailableCallAdapter } from './adapter';
import { FakeCallAdapter } from './fakeAdapter';

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

const client = jest.requireMock('../../api/callingClient') as {
  issueClientSession: jest.Mock;
  authorizeCall: jest.Mock;
  startCall: jest.Mock;
  stopCall: jest.Mock;
  getCall: jest.Mock;
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

const INSTRUCTION: StartInstruction = {
  attempt_id: 'attempt-1',
  destination_e164: '+441632960011',
  correlation: 'corr-1',
  max_seconds: 600,
  expires_at: '2026-09-13T12:10:00Z',
};

function build(overrides: Partial<ConstructorParameters<typeof CallSessionController>[0]> = {}) {
  const adapter = new FakeCallAdapter();
  const controller = new CallSessionController({
    accessToken: 'token',
    userId: 'user-1',
    deviceId: 'device-1',
    adapter,
    requestMicrophone: jest.fn(async () => 'granted' as const),
    now: () => 1_000,
    ...overrides,
  });
  return { adapter, controller };
}

beforeEach(() => {
  jest.clearAllMocks();
  client.issueClientSession.mockResolvedValue({
    token: 'provider-token',
    sip_identity: 'sip:user-1',
    expires_at: '2026-09-13T13:00:00Z',
  });
  client.authorizeCall.mockResolvedValue(ATTEMPT);
  client.startCall.mockResolvedValue(INSTRUCTION);
  client.stopCall.mockResolvedValue({ ...ATTEMPT, state: 'ended', end_reason: 'stopped' });
});

describe('the money is not held before the call can happen', () => {
  it('AC-47.1: microphone denial authorizes nothing', async () => {
    const { controller } = build({
      requestMicrophone: jest.fn(async () => 'denied' as const),
    });

    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    // The order matters more than the message: a denied microphone must be
    // discovered *before* a hold is taken, or a customer who declines the
    // permission prompt has money reserved against a call that never dialled.
    expect(client.authorizeCall).not.toHaveBeenCalled();
    expect(controller.snapshot().phase).toBe('failed');
    expect(controller.snapshot().failureCode).toBe('microphone_denied');
  });

  it('AC-47.1: a duplicate tap reuses one idempotency key, so one hold exists', async () => {
    const { controller } = build();

    await Promise.all([
      controller.place({ destination: '+441632960011', currency: 'NGN' }),
      controller.place({ destination: '+441632960011', currency: 'NGN' }),
    ]);

    expect(client.authorizeCall).toHaveBeenCalledTimes(1);
  });

  it('AC-47.1: a retry after a lost response reuses the first key', async () => {
    const { controller } = build();
    client.authorizeCall.mockRejectedValueOnce(
      new ApiError('network_error', 'offline', 0),
    );

    await controller.place({ destination: '+441632960011', currency: 'NGN' });
    await controller.retry();

    expect(client.authorizeCall).toHaveBeenCalledTimes(2);
    const [first] = client.authorizeCall.mock.calls[0];
    const [second] = client.authorizeCall.mock.calls[1];
    expect(second.idempotencyKey).toBe(first.idempotencyKey);
  });
});

describe('never leave an untracked billable call', () => {
  it('AC-47.2: a dial that throws still stops the attempt on the server', async () => {
    const { adapter, controller } = build();
    adapter.failNextDial('sdk_unavailable');

    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    // The hold exists the moment authorize returned. If the client gives up
    // without telling the server, the money stays held until an expiry sweeps
    // it, and the customer sees a balance they cannot spend.
    expect(client.stopCall).toHaveBeenCalledWith(
      expect.objectContaining({ attemptId: 'attempt-1' }),
    );
    expect(controller.snapshot().phase).toBe('failed');
  });

  it('AC-47.2: hangup reaches the server even when the adapter throws', async () => {
    const { adapter, controller } = build();
    await controller.place({ destination: '+441632960011', currency: 'NGN' });
    adapter.failNextHangup();

    await controller.hangup();

    expect(client.stopCall).toHaveBeenCalledTimes(1);
  });
});

describe('a previous account cannot be shown or controlled', () => {
  it('AC-47.2: a callback arriving after account switch is ignored', async () => {
    const { adapter, controller } = build();
    await controller.place({ destination: '+441632960011', currency: 'NGN' });
    adapter.emit({ kind: 'answered' });
    expect(controller.snapshot().phase).toBe('answered');

    controller.dispose();
    adapter.emit({ kind: 'ended', reason: 'remote_hangup' });

    // The SDK does not know an account changed and will keep talking. The
    // guard has to be ours: a disposed controller reports nothing and mutates
    // nothing, so the next user's screen cannot inherit this call.
    expect(controller.snapshot().phase).toBe('idle');
    expect(controller.snapshot().attemptId).toBeNull();
  });

  it('AC-47.2: a disposed controller refuses to place a new call', async () => {
    const { controller } = build();
    controller.dispose();

    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    expect(client.authorizeCall).not.toHaveBeenCalled();
  });
});

describe('failures a customer can act on', () => {
  it('AC-47.3: an expired session surfaces as an auth failure, not a call failure', async () => {
    const { controller } = build();
    client.authorizeCall.mockRejectedValueOnce(
      new ApiError('unauthenticated', 'expired', 401),
    );

    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    expect(controller.snapshot().failureCode).toBe('session_expired');
  });

  it('AC-47.3: insufficient funds is reported by its own code', async () => {
    const { controller } = build();
    client.authorizeCall.mockRejectedValueOnce(
      new ApiError('insufficient_funds', 'no credit', 409),
    );

    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    expect(controller.snapshot().failureCode).toBe('insufficient_funds');
    expect(client.startCall).not.toHaveBeenCalled();
  });

  it('AC-47.3: a revoked membership fails the work call without a hold', async () => {
    const { controller } = build();
    client.authorizeCall.mockRejectedValueOnce(
      // The server's own code for this, from app/calling/service.py. Using the
      // real one matters: a test that asserts against an invented code passes
      // while the app shows a stranger's error message.
      new ApiError('not_a_member', 'no longer a member', 403),
    );

    await controller.place({
      destination: '+441632960011',
      currency: 'NGN',
      organizationId: 'org-1',
    });

    expect(controller.snapshot().failureCode).toBe('not_permitted');
  });
});

describe('in-call controls follow what the adapter can actually do', () => {
  it('AC-47.1: DTMF is refused rather than silently dropped when unsupported', async () => {
    const adapter = new FakeCallAdapter({ dtmf: false });
    const { controller } = build({ adapter });
    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    const sent = await controller.sendDigit('5');

    expect(sent).toBe(false);
    expect(adapter.digits).toEqual([]);
  });

  it('AC-47.1: mute is tracked from the adapter, not assumed by the UI', async () => {
    const { adapter, controller } = build();
    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    await controller.setMuted(true);

    expect(adapter.muted).toBe(true);
    expect(controller.snapshot().muted).toBe(true);
  });

  it('AC-47.1: the elapsed estimate starts at answer, not at dial', async () => {
    let clock = 1_000;
    const { adapter, controller } = build({ now: () => clock });
    await controller.place({ destination: '+441632960011', currency: 'NGN' });
    clock = 5_000;
    adapter.emit({ kind: 'answered' });

    expect(controller.snapshot().answeredAt).toBe(5_000);
    // Ringing time is not billable and showing it as call time would make the
    // app's own estimate disagree with the receipt.
    expect(controller.snapshot().startedAt).toBe(1_000);
  });
});

describe('a build with no dialling path', () => {
  it('AC-47.3: refuses before asking for the microphone or taking a hold', async () => {
    const requestMicrophone = jest.fn(async () => 'granted' as const);
    const { controller } = build({
      adapter: new UnavailableCallAdapter(),
      requestMicrophone,
    });

    await controller.place({ destination: '+441632960011', currency: 'NGN' });

    // The order is the assertion. Prompting for a permission this build cannot
    // use trains people to decline it, and it is why chunk 08 kept RECORD_AUDIO
    // out of the Android manifest rather than declaring it early.
    expect(requestMicrophone).not.toHaveBeenCalled();
    expect(client.authorizeCall).not.toHaveBeenCalled();
    expect(controller.snapshot().failureCode).toBe('calling_unavailable');
  });
});
