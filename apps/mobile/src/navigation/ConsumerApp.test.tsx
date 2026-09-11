import React from 'react';
import {
  cleanup,
  render,
  screen,
  waitFor,
} from '@testing-library/react-native';
import { ConsumerApp } from './ConsumerApp';
import * as consumerClient from '../api/consumerClient';
import * as invitationClient from '../api/invitationClient';
import * as deepLinks from '../services/deepLinks';
import { setAppLocale } from '../i18n';
import { press } from '../testing/interact';

/**
 * US-37 chunk 18 — production navigation, service state and redemption.
 *
 * The tests are grouped by the acceptance criterion they carry rather than by
 * component, because the criteria are about journeys: "no dead ends" is not a
 * property of a screen.
 */

jest.mock('../api/consumerClient', () => ({
  ...jest.requireActual('../api/consumerClient'),
  getConsumerSession: jest.fn(),
  getServices: jest.fn(),
}));
jest.mock('../api/invitationClient');
jest.mock('../services/deepLinks', () => ({
  ...jest.requireActual('../services/deepLinks'),
  loadPendingLink: jest.fn(),
  clearPendingLink: jest.fn(),
  subscribeToDeepLinks: jest.fn(),
}));

const mockedSession = consumerClient.getConsumerSession as jest.Mock;
const mockedServices = consumerClient.getServices as jest.Mock;
const mockedPreview = invitationClient.previewInvitation as jest.Mock;
const mockedAccept = invitationClient.acceptInvitation as jest.Mock;
const mockedLoadPending = deepLinks.loadPendingLink as jest.Mock;
const mockedClearPending = deepLinks.clearPendingLink as jest.Mock;
const mockedSubscribe = deepLinks.subscribeToDeepLinks as jest.Mock;

function service(
  overrides: Partial<consumerClient.ServiceSummary> = {},
): consumerClient.ServiceSummary {
  return {
    order_item_id: 'item-1',
    order_id: 'order-1',
    order_reference: 'ORD-1',
    product_name: 'Travel 5GB',
    delivery: 'carrier_esim',
    owner: 'personal',
    organization_id: null,
    organization_name: null,
    payment_state: 'paid',
    provisioning_state: 'provisioned',
    installation_state: 'installed',
    activation_state: 'active',
    requires_installation: true,
    ready_to_use: true,
    granted_at: '2026-09-01T00:00:00Z',
    expires_at: null,
    expired: false,
    ...overrides,
  };
}

function sessionRead(
  overrides: Partial<consumerClient.ConsumerSession> = {},
): consumerClient.ConsumerSession {
  return {
    user_id: 'user-1',
    locale: 'en',
    verified_emails: ['me@example.test'],
    verified_phone_numbers: [],
    service_state: 'active',
    organizations: [],
    pending_invitations: 0,
    ...overrides,
  };
}

async function renderApp(
  props: Partial<React.ComponentProps<typeof ConsumerApp>> = {},
): Promise<void> {
  await render(
    <ConsumerApp
      accessToken="token"
      currentEmail="me@example.test"
      onSwitchAccount={jest.fn()}
      {...props}
    />,
  );
  // Both reads and the pending-link lookup are in flight on mount. Waiting for
  // the tab bar (or the invitation screen that replaces it) is what tells us
  // the first authenticated frame has settled.
  await waitFor(() =>
    expect(
      screen.queryByTestId('app-tab-bar') ??
        screen.queryByTestId('invitation-screen'),
    ).toBeTruthy(),
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockedLoadPending.mockResolvedValue(null);
  mockedClearPending.mockResolvedValue(undefined);
  mockedSubscribe.mockReturnValue(() => undefined);
  mockedSession.mockResolvedValue(sessionRead());
  mockedServices.mockResolvedValue({
    service_state: 'active',
    services: [service()],
  });
});

afterEach(async () => {
  await cleanup();
  await setAppLocale('en');
});

describe('AC-37.1 — four destinations, all reachable', () => {
  it('renders every tab and moves between them', async () => {
    await renderApp();

    expect(screen.getByTestId('tab-home')).toBeTruthy();
    expect(screen.getByTestId('tab-plans')).toBeTruthy();
    expect(screen.getByTestId('tab-my-line')).toBeTruthy();
    expect(screen.getByTestId('tab-account')).toBeTruthy();

    await press('tab-plans');

    await waitFor(() =>
      expect(
        screen.getByTestId('tab-plans').props.accessibilityState.selected,
      ).toBe(true),
    );
    expect(screen.getByTestId('tab-home').props.accessibilityState.selected).toBe(
      false,
    );
  });

  it('announces a waiting invitation on the tab that leads to it', async () => {
    mockedSession.mockResolvedValue(sessionRead({ pending_invitations: 2 }));

    await renderApp();

    expect(screen.getByTestId('tab-account-badge')).toBeTruthy();
    // A silent badge is invisible to a screen reader, so the count is in the
    // label rather than only in the dot.
    expect(screen.getByTestId('tab-account').props.accessibilityLabel).toBe(
      'Account, 2 invitations waiting',
    );
  });
});

describe('AC-37.5 — every state has a route out', () => {
  it('offers plans when the account has no service', async () => {
    mockedSession.mockResolvedValue(sessionRead({ service_state: 'none' }));
    mockedServices.mockResolvedValue({ service_state: 'none', services: [] });

    await renderApp();

    expect(screen.getByTestId('home-no-service')).toBeTruthy();
    await press('home-no-service-action');

    await waitFor(() =>
      expect(
        screen.getByTestId('tab-plans').props.accessibilityState.selected,
      ).toBe(true),
    );
  });

  it('leads with the install step when a provisioned line is not on the phone', async () => {
    mockedServices.mockResolvedValue({
      service_state: 'pending',
      services: [
        service({
          installation_state: 'not_installed',
          activation_state: 'pending',
          ready_to_use: false,
        }),
      ],
    });

    await renderApp();

    expect(screen.getByTestId('home-install')).toBeTruthy();
    await press('home-install-action');

    await waitFor(() =>
      expect(
        screen.getByTestId('tab-my-line').props.accessibilityState.selected,
      ).toBe(true),
    );
  });

  it('shows progress, not a spinner, while an order is still being provisioned', async () => {
    mockedServices.mockResolvedValue({
      service_state: 'pending',
      services: [
        service({
          provisioning_state: 'requested',
          installation_state: null,
          activation_state: null,
          requires_installation: false,
          ready_to_use: false,
        }),
      ],
    });

    await renderApp();

    // Setting up a line takes minutes. A spinner held that long reads as a
    // hang; this says what happened and that the app need not stay open.
    expect(screen.getByTestId('home-pending')).toBeTruthy();
    expect(screen.getByTestId('home-pending-action')).toBeTruthy();
  });

  it('gives a failed order somewhere to go rather than only saying it failed', async () => {
    mockedSession.mockResolvedValue(sessionRead({ service_state: 'none' }));
    mockedServices.mockResolvedValue({
      service_state: 'none',
      services: [
        service({
          provisioning_state: 'failed',
          installation_state: null,
          activation_state: null,
          ready_to_use: false,
        }),
      ],
    });

    await renderApp();

    expect(screen.getByTestId('home-failed')).toBeTruthy();
    expect(screen.getByTestId('home-failed-action')).toBeTruthy();
  });

  it('offers a retry when the service read itself fails', async () => {
    mockedServices.mockRejectedValueOnce(new Error('offline'));

    await renderApp();

    expect(screen.getByTestId('home-error')).toBeTruthy();

    mockedServices.mockResolvedValue({
      service_state: 'active',
      services: [service()],
    });
    await press('home-error-action');
    await waitFor(() => expect(screen.getByTestId('consumer-home')).toBeTruthy());
  });
});

describe('the internet-only journey', () => {
  it('never asks an internet-calling customer to install anything', async () => {
    // The calling amendment's requirement, at the screen. There is no profile
    // and no carrier line, so an install prompt would send the customer looking
    // for something that was never created.
    mockedServices.mockResolvedValue({
      service_state: 'active',
      services: [
        service({
          product_name: 'Calling 100',
          delivery: 'internet',
          installation_state: null,
          activation_state: null,
          requires_installation: false,
          ready_to_use: true,
        }),
      ],
    });

    await renderApp();

    expect(screen.queryByTestId('home-install')).toBeNull();
    expect(screen.getByText(/Internet calling/)).toBeTruthy();
  });
});

describe('AC-37 — personal and organization services stay distinguishable', () => {
  it('labels a work line with the organization that provides it', async () => {
    mockedServices.mockResolvedValue({
      service_state: 'active',
      services: [
        service({
          order_item_id: 'item-work',
          owner: 'organization',
          organization_id: 'org-1',
          organization_name: 'Acme Logistics',
        }),
        service({ order_item_id: 'item-personal' }),
      ],
    });

    await renderApp();

    expect(screen.getByText(/Provided by Acme Logistics/)).toBeTruthy();
    expect(screen.getByText(/Personal/)).toBeTruthy();
  });
});

describe('AC-37.3 / AC-37.4 — invitation links', () => {
  it('opens the invitation a cold launch left pending, before any url event', async () => {
    // The link arrived while the app was signed out. It was persisted then, and
    // this is the moment it finally becomes actionable.
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'pending',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'm•••e@example.test',
      expires_at: null,
      recipient_matches: true,
      already_a_member: false,
    });

    await renderApp();
    await waitFor(() => expect(screen.getByTestId('invitation-accept')).toBeTruthy());

    expect(mockedPreview).toHaveBeenCalledWith('token', 'tok');
  });

  it('refuses to bind an invitation addressed to somebody else', async () => {
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'pending',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'o•••r@acme.test',
      expires_at: null,
      recipient_matches: false,
      already_a_member: false,
    });

    await renderApp();
    await waitFor(() =>
      expect(screen.getByTestId('invitation-wrong-account')).toBeTruthy(),
    );

    // No accept button at all — the mismatch is shown *before* anything is
    // claimed, not as a 403 after the customer has already tapped "join".
    expect(screen.queryByTestId('invitation-accept-action')).toBeNull();
    expect(mockedAccept).not.toHaveBeenCalled();
  });

  it('explains an expired link instead of failing the screen', async () => {
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'expired',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'm•••e@example.test',
      expires_at: '2026-01-01T00:00:00Z',
      recipient_matches: true,
      already_a_member: false,
    });

    await renderApp();
    await waitFor(() => expect(screen.getByTestId('invitation-expired')).toBeTruthy());
    expect(screen.getByTestId('invitation-expired-action')).toBeTruthy();
  });

  it('says an already-used link was used, and by whom to ask if it was not them', async () => {
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'accepted',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'm•••e@example.test',
      expires_at: null,
      recipient_matches: true,
      already_a_member: false,
    });

    await renderApp();
    await waitFor(() => expect(screen.getByTestId('invitation-used')).toBeTruthy());
  });

  it('accepts a matching invitation and reloads the account', async () => {
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'pending',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'm•••e@example.test',
      expires_at: null,
      recipient_matches: true,
      already_a_member: false,
    });
    mockedAccept.mockResolvedValue({
      organization_id: 'org-1',
      user_id: 'user-1',
      role: 'member',
      status: 'active',
    });

    await renderApp();
    await waitFor(() => expect(screen.getByTestId('invitation-accept')).toBeTruthy());

    await press('invitation-accept-action');

    await waitFor(() =>
      expect(screen.getByTestId('invitation-accepted')).toBeTruthy(),
    );
    // Twice: once on mount, once after the membership exists. A work service
    // assigned on acceptance is invisible until the account is re-read.
    expect(mockedServices).toHaveBeenCalledTimes(2);
  });

  it('turns a replayed acceptance into an accurate screen, not a generic failure', async () => {
    // The customer taps twice, or had already used the link on another device.
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview
      .mockResolvedValueOnce({
        state: 'pending',
        organization_name: 'Acme Logistics',
        role: 'member',
        invited_kind: 'email',
        invited_value_masked: 'm•••e@example.test',
        expires_at: null,
        recipient_matches: true,
        already_a_member: false,
      })
      .mockResolvedValueOnce({
        state: 'accepted',
        organization_name: 'Acme Logistics',
        role: 'member',
        invited_kind: 'email',
        invited_value_masked: 'm•••e@example.test',
        expires_at: null,
        recipient_matches: true,
        already_a_member: true,
      });
    mockedAccept.mockRejectedValue(new Error('invitation_invalid'));

    await renderApp();
    await waitFor(() => expect(screen.getByTestId('invitation-accept')).toBeTruthy());

    await press('invitation-accept-action');

    await waitFor(() =>
      expect(screen.getByTestId('invitation-already-member')).toBeTruthy(),
    );
  });

  it('returns to the tabs and forgets the link when the invitation is dismissed', async () => {
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'expired',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'm•••e@example.test',
      expires_at: null,
      recipient_matches: true,
      already_a_member: false,
    });

    await renderApp();
    await waitFor(() => expect(screen.getByTestId('invitation-expired')).toBeTruthy());

    await press('invitation-expired-action');

    await waitFor(() => expect(screen.getByTestId('app-tab-bar')).toBeTruthy());
    // Otherwise the same dead invitation reappears on every foreground.
    expect(mockedClearPending).toHaveBeenCalled();
  });

  it('keeps the link when the customer leaves to sign in as the invited address', async () => {
    const onSwitchAccount = jest.fn();
    mockedLoadPending.mockResolvedValue({ kind: 'invitation', token: 'tok' });
    mockedPreview.mockResolvedValue({
      state: 'pending',
      organization_name: 'Acme Logistics',
      role: 'member',
      invited_kind: 'email',
      invited_value_masked: 'o•••r@acme.test',
      expires_at: null,
      recipient_matches: false,
      already_a_member: false,
    });

    await renderApp({ onSwitchAccount });
    await waitFor(() =>
      expect(screen.getByTestId('invitation-wrong-account')).toBeTruthy(),
    );

    await press('invitation-wrong-account-action');

    expect(onSwitchAccount).toHaveBeenCalledWith('o•••r@acme.test');
    // The link is what they are coming back for.
    expect(mockedClearPending).not.toHaveBeenCalled();
  });
});

describe('AC-37.6 — French is complete for every new surface', () => {
  it('renders the tab bar and the no-service state in French', async () => {
    await setAppLocale('fr');
    mockedSession.mockResolvedValue(sessionRead({ service_state: 'none' }));
    mockedServices.mockResolvedValue({ service_state: 'none', services: [] });

    await renderApp();

    expect(screen.getByText('Accueil')).toBeTruthy();
    expect(screen.getByText('Ma ligne')).toBeTruthy();
    expect(screen.getByTestId('home-no-service-title').props.children).toBe(
      "Vous n'avez pas encore de service",
    );
  });
});
