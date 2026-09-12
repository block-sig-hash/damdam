import React from 'react';
import { AppState, Platform, type AppStateStatus } from 'react-native';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react-native';
import { MyLineFlow } from './MyLineFlow';
import * as lineClient from '../../api/lineClient';
import { ApiError } from '../../api/http';
import * as screenPrivacy from '../../services/screenPrivacy';
import * as esimDownload from '../../services/esimDownload';
import { press } from '../../testing/interact';

/**
 * US-38 chunk 20 — My Line, installation and calling guidance.
 *
 * The tests are grouped by the mistake each one prevents. Two of those mistakes
 * are unusually expensive here and get the most attention:
 *
 * **Telling somebody their line works when it does not.** Installation,
 * activation and network attachment are separate facts that disagree in the
 * field, and the screen has to keep them apart under every combination.
 *
 * **Spending or leaking a one-time eSIM profile.** It cannot be re-downloaded,
 * so a double tap that burns a second grant, a code rendered before the screen
 * is protected, or a code that outlives its screen are all unrecoverable.
 */

jest.mock('../../api/lineClient', () => ({
  ...jest.requireActual('../../api/lineClient'),
  listLines: jest.fn(),
  getLine: jest.fn(),
  requestInstallationGrant: jest.fn(),
  redeemInstallationGrant: jest.fn(),
  confirmInstallation: jest.fn(),
}));
jest.mock('../../services/screenPrivacy', () => ({
  protectScreen: jest.fn(),
  releaseScreen: jest.fn(),
}));
jest.mock('../../services/esimDownload', () => ({
  downloadEsimProfile: jest.fn(),
}));

const mockedList = lineClient.listLines as jest.Mock;
const mockedGet = lineClient.getLine as jest.Mock;
const mockedGrant = lineClient.requestInstallationGrant as jest.Mock;
const mockedRedeem = lineClient.redeemInstallationGrant as jest.Mock;
const mockedConfirm = lineClient.confirmInstallation as jest.Mock;
const mockedProtect = screenPrivacy.protectScreen as jest.Mock;
const mockedRelease = screenPrivacy.releaseScreen as jest.Mock;
const mockedDownload = esimDownload.downloadEsimProfile as jest.Mock;

const ENTITLEMENT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const LPA = 'LPA:1$rsp.example.test$MATCHING-ID-42';

function line(overrides: Partial<lineClient.LineDetail> = {}): lineClient.LineDetail {
  return {
    entitlement_id: ENTITLEMENT_ID,
    order_id: 'order-1',
    order_reference: 'OR-ABCD1234',
    order_item_id: 'item-1',
    product_id: 'product-1',
    product_name: 'Nigeria 5GB + calls',
    delivery: 'carrier_esim',
    ready_to_use: false,
    number_status: 'assigned',
    assigned_number: {
      e164: '+2349012345678',
      country: 'NG',
      assigned_at: '2026-09-12T09:00:00Z',
    },
    installation: {
      state: 'not_installed',
      installed_at: null,
      profile_released_at: '2026-09-12T09:10:00Z',
      credential_available: true,
      credential_unavailable_reason: null,
      delivery_count: 0,
      one_time_use: true,
      reinstall_available: false,
      reinstall_blocked_reason: 'one_time_profile',
    },
    line: {
      carrier: 'telnyx',
      activation_state: 'active',
      network_state: 'unknown',
      network_state_observed_at: null,
      provider_status: 'active',
      provider_status_observed_at: '2026-09-12T09:10:00Z',
      voice_enabled: true,
      voice_enabled_observed_at: '2026-09-12T09:10:00Z',
    },
    usage: {
      data_bytes_total: 5 * 1024 * 1024 * 1024,
      data_bytes_used: 1024 * 1024 * 1024,
      data_bytes_remaining: 4 * 1024 * 1024 * 1024,
      voice_seconds_total: 3600,
      voice_seconds_used: 600,
      voice_seconds_remaining: 3000,
      observed_at: new Date(Date.now() - 5 * 60_000).toISOString(),
      freshness: 'fresh',
      has_provisional: false,
      expires_at: null,
      expired: false,
    },
    restriction: {
      suspended: false,
      enforcement: 'none',
      control_state: 'requested',
      requested_limit_bytes: null,
      confirmed_limit_bytes: null,
      detail: null,
    },
    top_ups: {
      applied_data_bytes: 0,
      applied_voice_seconds: 0,
      applied_extra_days: 0,
      pending_count: 0,
    },
    tariff: {
      version: 1,
      currency: 'NGN',
      destinations: [
        {
          country: 'NG',
          destination_kind: 'mobile',
          per_minute_amount: '25.500000',
          setup_amount: '0.00',
          increment_seconds: 60,
          minimum_seconds: 30,
        },
      ],
    },
    calling: {
      native_available: true,
      native_unavailable_reason: null,
      internet_dialer_enabled: false,
      internet_dialer_reason: 'v04_not_accepted',
      requires_line_selection: true,
    },
    ...overrides,
  };
}

function summary(
  overrides: Partial<lineClient.LineSummary> = {},
): lineClient.LineSummary {
  return {
    entitlement_id: ENTITLEMENT_ID,
    order_id: 'order-1',
    order_reference: 'OR-ABCD1234',
    product_name: 'Nigeria 5GB + calls',
    delivery: 'carrier_esim',
    number_status: 'assigned',
    e164: '+2349012345678',
    activation_state: 'active',
    installation_state: 'not_installed',
    ready_to_use: false,
    expires_at: null,
    expired: false,
    ...overrides,
  };
}

async function renderFlow(
  props: Partial<React.ComponentProps<typeof MyLineFlow>> = {},
) {
  // `act`-wrapped, matching chunk 19's purchase suite: the mount effect resolves
  // across several microtasks, and an unwrapped render leaves those updates
  // outside React's act scope — 200 lines of console noise around a passing
  // test. Flushing with a bare `act` *after* render is measurably worse here.
  await act(async () => {
    render(
      <MyLineFlow accessToken="token" onBrowsePlans={jest.fn()} {...props} />,
    );
  });
  await waitFor(() =>
    expect(
      screen.queryByTestId('my-line') ??
        screen.queryByTestId('my-line-list') ??
        screen.queryByTestId('my-line-loading') ??
        screen.queryByTestId('my-line-empty'),
    ).toBeTruthy(),
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(AppState, 'addEventListener').mockReturnValue({ remove: jest.fn() });
  Platform.OS = 'android';
  mockedList.mockResolvedValue({ lines: [summary()] });
  mockedGet.mockResolvedValue(line());
  mockedProtect.mockResolvedValue('protected');
  mockedRelease.mockResolvedValue(undefined);
  mockedGrant.mockResolvedValue({
    grant_token: 'grant-token-1',
    expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    one_time_use: true,
    delivery_count: 0,
  });
  mockedRedeem.mockResolvedValue({
    entitlement_id: ENTITLEMENT_ID,
    lpa: LPA,
    one_time_use: true,
    delivery_count: 1,
    reinstall_available: false,
  });
  mockedConfirm.mockResolvedValue(
    line({ installation: { ...line().installation!, state: 'installed' } }),
  );
  mockedDownload.mockResolvedValue('invoked');
});

afterEach(async () => {
  await cleanup();
});

describe('the four states are reported separately (AC-38.3)', () => {
  it('waits for a missing carrier profile instead of reporting ready', async () => {
    mockedGet.mockResolvedValue(line({ installation: null, line: null }));
    await renderFlow();
    expect(screen.getByTestId('my-line-next-awaiting')).toBeTruthy();
    expect(screen.queryByTestId('my-line-next-ready')).toBeNull();
  });

  it('shows the number, installation, activation, network and voice facts', async () => {
    await renderFlow();

    expect(screen.getByTestId('my-line-number-value')).toHaveTextContent(
      /\+2349012345678/,
    );
    expect(screen.getByTestId('my-line-pill-installation')).toBeTruthy();
    expect(screen.getByTestId('my-line-pill-activation')).toBeTruthy();
    expect(screen.getByTestId('my-line-pill-network')).toBeTruthy();
    expect(screen.getByTestId('my-line-pill-voice')).toBeTruthy();
  });

  it('does not report the network as connected because the line is active', async () => {
    mockedGet.mockResolvedValue(
      line({
        installation: { ...line().installation!, state: 'installed' },
        line: { ...line().line!, activation_state: 'active', network_state: 'unknown' },
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-pill-network')).toHaveTextContent(
      /Not reported/,
    );
  });

  it('an installed profile on an inactive line is a wait, not a ready line', async () => {
    mockedGet.mockResolvedValue(
      line({
        installation: { ...line().installation!, state: 'installed' },
        line: { ...line().line!, activation_state: 'pending' },
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-next-activation')).toHaveTextContent(
      /separate step we don't control/,
    );
    expect(screen.queryByTestId('my-line-next-ready')).toBeNull();
  });

  it('a profile that has not been issued offers a wait, not an install button', async () => {
    mockedGet.mockResolvedValue(
      line({
        installation: {
          ...line().installation!,
          credential_available: false,
          credential_unavailable_reason: 'profile_not_issued',
        },
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-next-awaiting')).toBeTruthy();
    expect(screen.queryByTestId('my-line-next-install')).toBeNull();
  });

  it('an internet grant shows no profile and no line, not empty ones', async () => {
    mockedGet.mockResolvedValue(
      line({
        delivery: 'internet',
        installation: null,
        line: null,
        restriction: null,
        number_status: 'not_included',
        assigned_number: null,
        ready_to_use: true,
        calling: {
          native_available: false,
          native_unavailable_reason: 'no_carrier_line',
          internet_dialer_enabled: false,
          internet_dialer_reason: 'v04_not_accepted',
          requires_line_selection: false,
        },
      }),
    );

    await renderFlow();

    expect(screen.queryByTestId('my-line-states')).toBeNull();
    expect(screen.getByTestId('my-line-number-absent')).toHaveTextContent(
      /doesn't include a phone number/,
    );
    expect(screen.queryByTestId('my-line-calling-guide')).toBeNull();
  });
});

describe('usage says how much it can be trusted (AC-38.3)', () => {
  it('never draws a balance nobody has measured', async () => {
    mockedGet.mockResolvedValue(
      line({
        usage: { ...line().usage, observed_at: null, freshness: 'unknown' },
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-usage-data')).toHaveTextContent(
      /hasn't reported any usage/,
    );
  });

  it('warns when the reading is old rather than showing it plainly', async () => {
    mockedGet.mockResolvedValue(
      line({
        usage: {
          ...line().usage,
          observed_at: new Date(Date.now() - 9 * 60 * 60_000).toISOString(),
          freshness: 'stale',
        },
      }),
    );

    await renderFlow();

    const meter = screen.getByTestId('my-line-usage-data');
    expect(meter).toHaveTextContent(/Updated 9 h ago/);
    expect(meter).toHaveTextContent(/real balance may be lower/);
  });

  it('says a paid top-up is not usable yet rather than staying silent', async () => {
    mockedGet.mockResolvedValue(
      line({ top_ups: { ...line().top_ups, pending_count: 1 } }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-pending-top-up')).toHaveTextContent(
      /isn't usable yet/,
    );
  });

  it('says nothing at the network is capping the line', async () => {
    await renderFlow();

    expect(screen.getByTestId('my-line-no-enforcement')).toHaveTextContent(
      /Nothing at the network is capping/,
    );
  });
});

describe('suspension and expiry lead somewhere (AC-38.5)', () => {
  it('a suspended line says what is wrong and shows the supplier detail', async () => {
    mockedGet.mockResolvedValue(
      line({
        line: { ...line().line!, activation_state: 'suspended' },
        restriction: {
          ...line().restriction!,
          suspended: true,
          detail: 'allowance exhausted',
        },
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-next-suspended')).toHaveTextContent(
      /allowance exhausted/,
    );
  });

  it('an expired line offers a plan rather than a dead end', async () => {
    const onBrowsePlans = jest.fn();
    mockedGet.mockResolvedValue(
      line({ usage: { ...line().usage, expired: true } }),
    );

    await renderFlow({ onBrowsePlans });
    await press('my-line-next-expired-action');

    expect(onBrowsePlans).toHaveBeenCalled();
  });
});

describe('the activation code is protected before it exists (AC-38.1)', () => {
  it('does not request material while protection is still pending', async () => {
    mockedProtect.mockImplementationOnce(() => new Promise(() => {}));
    await renderFlow();
    await press('my-line-next-install-action');
    await press('install-reveal-action');
    expect(mockedGrant).not.toHaveBeenCalled();
  });

  it('discards a late credential after leaving and reopening installation', async () => {
    let finish!: (value: lineClient.InstallationCredential) => void;
    mockedRedeem.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    await renderFlow();
    await press('my-line-next-install-action');
    await press('install-reveal-action');
    await press('install-back');
    await press('my-line-next-install-action');
    await act(async () => finish({ entitlement_id: ENTITLEMENT_ID, lpa: LPA,
      one_time_use: true, delivery_count: 1, reinstall_available: false }));
    expect(screen.queryByTestId('install-code')).toBeNull();
  });

  it('clears revealed material when the app becomes inactive', async () => {
    let change!: (state: AppStateStatus) => void;
    const listener = jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, callback) => {
      change = callback;
      return { remove: jest.fn() };
    });
    await renderFlow();
    await press('my-line-next-install-action');
    await press('install-reveal-action');
    expect(screen.getByTestId('install-code')).toBeTruthy();
    await act(async () => change('inactive'));
    expect(screen.queryByTestId('install-code')).toBeNull();
    listener.mockRestore();
  });

  it('keeps the requested line open when its navigation intent is consumed', async () => {
    mockedList.mockResolvedValue({ lines: [summary(), summary({ entitlement_id: 'other' })] });
    function Host() {
      const [requested, setRequested] = React.useState<string | null>(ENTITLEMENT_ID);
      return <MyLineFlow accessToken="token" initialEntitlementId={requested}
        onEntitlementOpened={() => setRequested(null)} onBrowsePlans={jest.fn()} />;
    }
    await act(async () => { render(<Host />); });
    expect(screen.getByTestId('my-line')).toBeTruthy();
    expect(mockedList).not.toHaveBeenCalled();
  });

  it('opens the install screen without fetching or showing the profile', async () => {
    await renderFlow();
    await press('my-line-next-install-action');

    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    expect(mockedGrant).not.toHaveBeenCalled();
    expect(screen.queryByText(LPA)).toBeNull();
  });

  it('engages screen protection before the code is requested', async () => {
    const order: string[] = [];
    mockedProtect.mockImplementation(async () => {
      order.push('protect');
      return 'protected';
    });
    mockedGrant.mockImplementation(async () => {
      order.push('grant');
      return {
        grant_token: 'grant-token-1',
        expires_at: new Date().toISOString(),
        one_time_use: true,
        delivery_count: 0,
      };
    });

    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');

    await waitFor(() => expect(screen.getByTestId('install-code')).toBeTruthy());
    expect(order).toEqual(['protect', 'grant']);
  });

  it('warns instead of pretending, where the platform cannot block screenshots', async () => {
    Platform.OS = 'ios';
    mockedProtect.mockResolvedValue('unsupported');

    await renderFlow();
    await press('my-line-next-install-action');

    await waitFor(() =>
      expect(screen.getByTestId('install-privacy-unprotected')).toBeTruthy(),
    );
    expect(screen.getByTestId('install-privacy-unprotected')).toHaveTextContent(
      /doesn't let us block screenshots/,
    );
    expect(screen.queryByTestId('install-privacy-protected')).toBeNull();
  });

  it('warns when protection was available and failed', async () => {
    mockedProtect.mockResolvedValue('failed');

    await renderFlow();
    await press('my-line-next-install-action');

    await waitFor(() =>
      expect(screen.getByTestId('install-privacy-unprotected')).toHaveTextContent(
        /couldn't block screenshots/,
      ),
    );
  });

  it('releases the protection on the way out, so later screens are capturable', async () => {
    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());

    await press('install-back');

    await waitFor(() => expect(mockedRelease).toHaveBeenCalled());
    expect(screen.getByTestId('my-line')).toBeTruthy();
  });
});

describe('a one-time profile is spent once (AC-38.1)', () => {
  it('splits the code into the two fields a phone actually asks for', async () => {
    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');

    await waitFor(() => expect(screen.getByTestId('install-smdp')).toBeTruthy());
    expect(screen.getByTestId('install-smdp')).toHaveTextContent(
      /rsp\.example\.test/,
    );
    expect(screen.getByTestId('install-activation-code')).toHaveTextContent(
      /MATCHING-ID-42/,
    );
  });

  it('offers the whole string rather than guessing an unexpected shape', async () => {
    mockedRedeem.mockResolvedValue({
      entitlement_id: ENTITLEMENT_ID,
      lpa: 'SOMETHING-ELSE',
      one_time_use: true,
      delivery_count: 1,
      reinstall_available: false,
    });

    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');

    await waitFor(() =>
      expect(screen.getByTestId('install-whole-code')).toHaveTextContent(
        /SOMETHING-ELSE/,
      ),
    );
    expect(screen.queryByTestId('install-smdp')).toBeNull();
  });

  it('spends one grant for a double tap on reveal', async () => {
    let resolveGrant: (value: lineClient.InstallationGrant) => void = () => {};
    mockedGrant.mockImplementation(
      () =>
        new Promise<lineClient.InstallationGrant>(resolve => {
          resolveGrant = resolve;
        }),
    );

    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());

    // Both taps in one act: the second arrives before React re-renders with the
    // button disabled, which is what a real double tap is.
    await act(async () => {
      fireEvent.press(screen.getByTestId('install-reveal-action'));
      fireEvent.press(screen.getByTestId('install-reveal-action'));
    });

    expect(mockedGrant).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveGrant({
        grant_token: 'grant-token-1',
        expires_at: new Date().toISOString(),
        one_time_use: true,
        delivery_count: 0,
      });
    });
  });

  it('warns when the code has been shown before', async () => {
    mockedRedeem.mockResolvedValue({
      entitlement_id: ENTITLEMENT_ID,
      lpa: LPA,
      one_time_use: true,
      delivery_count: 2,
      reinstall_available: false,
    });

    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');

    await waitFor(() =>
      expect(screen.getByTestId('install-shown-before')).toHaveTextContent(
        /already be installed on another device/,
      ),
    );
  });

  it('never offers a reinstall, and says why', async () => {
    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');

    await waitFor(() =>
      expect(screen.getByTestId('install-no-reinstall')).toHaveTextContent(
        /only be downloaded once/,
      ),
    );
  });

  it('explains a refused grant instead of showing a blank screen', async () => {
    mockedRedeem.mockRejectedValue(
      new ApiError(
        'grant_not_redeemable',
        'That eSIM link is no longer usable.',
        409,
      ),
    );

    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');

    await waitFor(() =>
      expect(screen.getByTestId('install-error')).toHaveTextContent(
        /no longer usable/,
      ),
    );
  });
});

describe('only the device reports an installation (AC-38.1, AC-38.5)', () => {
  it('invoking the platform installer is not an installation', async () => {
    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');
    await waitFor(() => expect(screen.getByTestId('install-direct')).toBeTruthy());

    await press('install-direct');

    await waitFor(() => expect(screen.getByTestId('install-invoked')).toBeTruthy());
    expect(mockedDownload).toHaveBeenCalledWith(LPA);
    // The request was accepted by the system. Nothing has been confirmed.
    expect(mockedConfirm).not.toHaveBeenCalled();
  });

  it('records a failed install as not installed', async () => {
    mockedConfirm.mockResolvedValue(line());

    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');
    await waitFor(() => expect(screen.getByTestId('install-failed')).toBeTruthy());

    await press('install-failed');

    await waitFor(() =>
      expect(mockedConfirm).toHaveBeenCalledWith('token', ENTITLEMENT_ID, false),
    );
  });

  it('a confirmed install returns to the line and drops the code', async () => {
    await renderFlow();
    await press('my-line-next-install-action');
    await waitFor(() => expect(screen.getByTestId('install-reveal')).toBeTruthy());
    await press('install-reveal-action');
    await waitFor(() => expect(screen.getByTestId('install-confirm')).toBeTruthy());

    await press('install-confirm');

    await waitFor(() => expect(screen.getByTestId('my-line')).toBeTruthy());
    expect(mockedConfirm).toHaveBeenCalledWith('token', ENTITLEMENT_ID, true);
    // The code does not survive the screen that showed it.
    expect(screen.queryByText(LPA)).toBeNull();
    expect(mockedRelease).toHaveBeenCalled();
  });
});

describe('calling guidance claims nothing it cannot see (AC-38.4)', () => {
  it('offers no in-app dialer and says calls go through the phone', async () => {
    await renderFlow();

    expect(screen.getByTestId('my-line-internet-dialer')).toHaveTextContent(
      /phone's own dialer/,
    );
  });

  it('gives per-platform steps and refuses to claim a call was placed', async () => {
    await renderFlow();
    await press('my-line-calling-guide');

    await waitFor(() => expect(screen.getByTestId('calling-guide')).toBeTruthy());
    expect(screen.getByTestId('calling-guide-caveat')).toHaveTextContent(
      /isn't proof a call went out/,
    );
    expect(screen.getByTestId('calling-guide-number')).toHaveTextContent(
      /\+2349012345678/,
    );
  });

  it('says why a data-only line cannot call', async () => {
    mockedGet.mockResolvedValue(
      line({
        line: { ...line().line!, voice_enabled: false },
        calling: {
          native_available: false,
          native_unavailable_reason: 'voice_not_enabled',
          internet_dialer_enabled: false,
          internet_dialer_reason: 'v04_not_accepted',
          requires_line_selection: true,
        },
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('my-line-native-unavailable')).toHaveTextContent(
      /carries data only/,
    );
  });
});

describe('what happens when there is nothing to show', () => {
  it('offers plans when the account holds no line', async () => {
    mockedList.mockResolvedValue({ lines: [] });

    await renderFlow();

    expect(screen.getByTestId('my-line-empty')).toBeTruthy();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it('lists lines when there is more than one', async () => {
    mockedList.mockResolvedValue({
      lines: [summary(), summary({ entitlement_id: 'second', e164: '+2349000000001' })],
    });

    await renderFlow();

    expect(screen.getByTestId(`my-line-card-${ENTITLEMENT_ID}`)).toBeTruthy();
    expect(screen.getByTestId('my-line-card-second')).toBeTruthy();
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it('explains a line it cannot open', async () => {
    mockedGet.mockRejectedValue(
      new ApiError(
        'line_not_found',
        'We could not find that line on your account.',
        404,
      ),
    );

    await renderFlow({ initialEntitlementId: ENTITLEMENT_ID });

    await waitFor(() =>
      expect(screen.getByTestId('my-line-loading-state')).toHaveTextContent(
        /could not find that line/,
      ),
    );
  });
});
