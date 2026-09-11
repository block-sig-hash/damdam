import React from 'react';
import { Linking } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { PurchaseFlow } from './PurchaseFlow';
import * as checkoutClient from '../../api/checkoutClient';
import { ApiError } from '../../api/http';
import * as esimCompatibility from '../../utils/esimCompatibility';
import { PENDING_ORDER_KEY } from '../../services/pendingOrder';
import { press } from '../../testing/interact';

/**
 * US-37 chunk 19 — the consumer purchase journey.
 *
 * Grouped by the failure each test prevents rather than by screen, because
 * every one of them is a sequence: "a lost response must not become a second
 * order" is not a property of a component.
 *
 * `AsyncStorage` is the real in-memory mock rather than a jest.fn, and the
 * restart tests genuinely unmount and re-render. A stubbed store would pass
 * while proving nothing about the case that matters — the app is gone, and the
 * only thing left is what was written to disk before the customer left.
 */

jest.mock('../../api/checkoutClient', () => ({
  ...jest.requireActual('../../api/checkoutClient'),
  listMarkets: jest.fn(),
  listProducts: jest.fn(),
  createQuote: jest.fn(),
  getPaymentMethods: jest.fn(),
  placeCheckout: jest.fn(),
  getOrder: jest.fn(),
}));
// A factory, not an automock: automocking would still load the real module to
// derive its shape, and `react-native-device-info` builds a NativeEventEmitter
// at import time that has no native side under Jest.
jest.mock('../../utils/esimCompatibility', () => ({
  checkEsimCompatibility: jest.fn(),
}));

const mockedMarkets = checkoutClient.listMarkets as jest.Mock;
const mockedProducts = checkoutClient.listProducts as jest.Mock;
const mockedQuote = checkoutClient.createQuote as jest.Mock;
const mockedMethods = checkoutClient.getPaymentMethods as jest.Mock;
const mockedCheckout = checkoutClient.placeCheckout as jest.Mock;
const mockedOrder = checkoutClient.getOrder as jest.Mock;
const mockedCompatibility =
  esimCompatibility.checkEsimCompatibility as jest.Mock;

const MARKET: checkoutClient.MarketSummary = {
  country: 'NG',
  currency: 'NGN',
  seller_name: 'DamDam Ltd',
};

const PRODUCT_ID = '11111111-1111-4111-8111-111111111111';
const QUOTE_ID = '22222222-2222-4222-8222-222222222222';
const ORDER_ID = '33333333-3333-4333-8333-333333333333';

function product(
  overrides: Partial<checkoutClient.ProductSummary> = {},
): checkoutClient.ProductSummary {
  return {
    product_id: PRODUCT_ID,
    sku: 'NG-DATA-5GB',
    name: 'Nigeria 5GB',
    kind: 'bundle',
    currency: 'NGN',
    amount: '12000.00',
    data_bytes: 5 * 1024 * 1024 * 1024,
    voice_seconds: 3600,
    validity_days: 30,
    requires_esim: true,
    requires_unlocked_device: true,
    device_notes: null,
    number_type: 'mobile',
    number_country: 'NG',
    number_assignment: 'new_assigned',
    coverage_countries: ['NG', 'GH'],
    call_destinations: [
      {
        country: 'NG',
        destination_kind: 'mobile',
        per_minute_amount: '15.5000',
        setup_amount: '0.00',
        increment_seconds: 60,
      },
    ],
    tariff_version: 1,
    purchasable: true,
    unavailable_reason: null,
    ...overrides,
  };
}

function quote(
  overrides: Partial<checkoutClient.QuoteResponse> = {},
): checkoutClient.QuoteResponse {
  return {
    quote_id: QUOTE_ID,
    reference: 'QT-ABC',
    status: 'issued',
    currency: 'NGN',
    subtotal_amount: '12000.00',
    tax_amount: '0.00',
    fee_amount: '0.00',
    total_amount: '12000.00',
    tax_configuration_reference: null,
    seller_name: 'DamDam Ltd',
    issued_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
    items: [
      {
        product_id: PRODUCT_ID,
        product_name: 'Nigeria 5GB',
        quantity: 1,
        unit_amount: '12000.00',
        line_amount: '12000.00',
        recipient_user_id: null,
      },
    ],
    ...overrides,
  };
}

function order(
  overrides: Partial<checkoutClient.OrderResponse> = {},
): checkoutClient.OrderResponse {
  return {
    order_id: ORDER_ID,
    reference: 'OR-DEADBEEF',
    currency: 'NGN',
    total_amount: '12000.00',
    payment_state: 'unpaid',
    placed_at: new Date().toISOString(),
    items: [
      {
        order_item_id: 'item-1',
        product_id: PRODUCT_ID,
        product_name: 'Nigeria 5GB',
        unit_currency: 'NGN',
        unit_amount: '12000.00',
        provisioning_state: 'not_started',
        recipient_user_id: null,
      },
    ],
    fulfilment_state: 'not_started',
    ...overrides,
  };
}

function methods(
  overrides: Partial<checkoutClient.PaymentMethodsResponse> = {},
): checkoutClient.PaymentMethodsResponse {
  return {
    methods: ['card', 'bank_transfer'],
    wallets: [
      { wallet: 'apple_pay', available: false, reason: 'no_processor_selected' },
      { wallet: 'google_pay', available: false, reason: 'no_processor_selected' },
    ],
    card_fallback_required: true,
    collection_enabled: true,
    collection_blocked_reason: null,
    ...overrides,
  };
}

async function renderFlow(
  props: Partial<React.ComponentProps<typeof PurchaseFlow>> = {},
) {
  // Wrapped in `act`: the mount effect resolves the device check and the first
  // reads across several microtasks, and an unwrapped `render` leaves those
  // state updates outside React's act scope — which under React 19 is 200 lines
  // of console noise around a passing test.
  let rendered: ReturnType<typeof render> | undefined;
  await act(async () => {
    rendered = render(
      <PurchaseFlow accessToken="token" onOpenMyLine={jest.fn()} {...props} />,
    );
  });
  await waitFor(() =>
    expect(
      screen.queryByTestId('plan-list') ??
        screen.queryByTestId('order-status') ??
        screen.queryByTestId('order-loading') ??
        screen.queryByTestId('plans-no-market') ??
        screen.queryByTestId('plans-error'),
    ).toBeTruthy(),
  );
  return rendered;
}

/** Browse → choose → review, the prefix every payment test needs. */
async function reachReview(): Promise<void> {
  await renderFlow();
  await press(`plan-${PRODUCT_ID}-choose`);
  await waitFor(() => expect(screen.getByTestId('quote-review')).toBeTruthy());
}

beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
  mockedCompatibility.mockResolvedValue({
    platform: 'android',
    deviceModel: 'Pixel 8',
    osVersion: '14',
    supported: true,
  });
  mockedMarkets.mockResolvedValue({ markets: [MARKET] });
  mockedProducts.mockResolvedValue({
    country: 'NG',
    currency: 'NGN',
    products: [product()],
  });
  mockedQuote.mockResolvedValue(quote());
  mockedMethods.mockResolvedValue(methods());
  mockedOrder.mockResolvedValue(order());
  jest.spyOn(Linking, 'openURL').mockResolvedValue(true);
});

afterEach(async () => {
  await cleanup();
  jest.restoreAllMocks();
});

describe('browsing states what is being sold (AC-37.4)', () => {
  it('shows price, currency, contents, number policy and priced destinations', async () => {
    await renderFlow();

    expect(screen.getByTestId(`plan-${PRODUCT_ID}-price`)).toHaveTextContent(
      'NGN 12000.00',
    );
    expect(screen.getByTestId(`plan-${PRODUCT_ID}-includes`)).toHaveTextContent(/5 GB data/);
    expect(screen.getByTestId(`plan-${PRODUCT_ID}-includes`)).toHaveTextContent(/60 min of calls/);
    expect(screen.getByTestId(`plan-${PRODUCT_ID}-number`)).toHaveTextContent(/A new mobile number in NG is assigned/);
    expect(
      screen.getByTestId(`plan-${PRODUCT_ID}-destinations`),
    ).toHaveTextContent(/Calls priced to: NG/);
  });

  it('says no number is included rather than staying silent about it', async () => {
    mockedProducts.mockResolvedValue({
      country: 'NG',
      currency: 'NGN',
      products: [product({ number_type: 'none', number_assignment: 'none' })],
    });

    await renderFlow();

    expect(screen.getByTestId(`plan-${PRODUCT_ID}-number`)).toHaveTextContent(/No phone number is included/);
  });

  it('keeps an unsellable plan on screen with the reason, rather than hiding it', async () => {
    mockedProducts.mockResolvedValue({
      country: 'NG',
      currency: 'NGN',
      products: [
        product({ purchasable: false, unavailable_reason: 'no_verified_supplier' }),
      ],
    });

    await renderFlow();

    expect(screen.getByTestId(`plan-${PRODUCT_ID}-price`)).toBeTruthy();
    expect(
      screen.getByTestId(`plan-${PRODUCT_ID}-unavailable`),
    ).toHaveTextContent(/don't have a verified supplier/);
    expect(screen.queryByTestId(`plan-${PRODUCT_ID}-choose`)).toBeNull();
  });

  it('renders a reason it has no copy for as a sentence, never as a raw code', async () => {
    mockedProducts.mockResolvedValue({
      country: 'NG',
      currency: 'NGN',
      products: [
        product({ purchasable: false, unavailable_reason: 'some_future_rule' }),
      ],
    });

    await renderFlow();

    const banner = screen.getByTestId(`plan-${PRODUCT_ID}-unavailable`);
    expect(banner).toHaveTextContent(/isn't available to buy right now/);
    expect(banner).not.toHaveTextContent(/some_future_rule/);
  });
});

describe('device compatibility is guidance, not a verdict (AC-37.4)', () => {
  it('warns about an unsupported device and offers the checks a person can make', async () => {
    mockedCompatibility.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone 8',
      osVersion: '16',
      supported: false,
    });
    mockedProducts.mockResolvedValue({
      country: 'NG',
      currency: 'NGN',
      products: [
        product({
          purchasable: false,
          unavailable_reason: 'device_not_esim_capable',
        }),
      ],
    });

    await renderFlow();

    const banner = screen.getByTestId('device-incapable');
    expect(banner).toHaveTextContent(/couldn't confirm/);
    expect(banner).toHaveTextContent(/\*#06#/);
    expect(screen.getByTestId(`plan-${PRODUCT_ID}-unavailable`)).toHaveTextContent(/can't take an eSIM/);
  });

  it('never dead-ends a capable phone the check did not recognize', async () => {
    mockedCompatibility.mockResolvedValue({
      platform: 'ios',
      deviceModel: 'iPhone 8',
      osVersion: '16',
      supported: false,
    });
    mockedProducts
      .mockResolvedValueOnce({
        country: 'NG',
        currency: 'NGN',
        products: [
          product({
            purchasable: false,
            unavailable_reason: 'device_not_esim_capable',
          }),
        ],
      })
      .mockResolvedValue({
        country: 'NG',
        currency: 'NGN',
        products: [product()],
      });

    await renderFlow();
    await press('device-incapable-action');

    await waitFor(() =>
      expect(screen.getByTestId(`plan-${PRODUCT_ID}-choose`)).toBeTruthy(),
    );
    expect(mockedProducts).toHaveBeenLastCalledWith('NG', 'NGN', {
      supports_esim: true,
      is_unlocked: null,
    });
    expect(screen.getByTestId('device-customer-confirmed')).toBeTruthy();
  });

  it('reports a carrier lock as unknown, because no phone tells us', async () => {
    await renderFlow();

    expect(screen.getByTestId('device-lock-guidance')).toHaveTextContent(/can't tell whether your phone is locked/);
    expect(mockedProducts).toHaveBeenCalledWith(
      'NG',
      'NGN',
      expect.objectContaining({ is_unlocked: null }),
    );
  });

  it('treats a check that could not run as "not checked", never as incapable', async () => {
    mockedCompatibility.mockRejectedValue(new Error('native module missing'));

    await renderFlow();

    expect(mockedProducts).toHaveBeenCalledWith('NG', 'NGN', {
      supports_esim: null,
      is_unlocked: null,
    });
    expect(screen.queryByTestId('device-incapable')).toBeNull();
  });
});

describe('the quote is what gets charged (AC-37.4)', () => {
  it('renders the server total verbatim and does not recompute it', async () => {
    mockedQuote.mockResolvedValue(
      quote({ subtotal_amount: '12000.00', fee_amount: '250.50', total_amount: '12250.50' }),
    );

    await reachReview();

    expect(screen.getByTestId('quote-total')).toHaveTextContent('NGN 12250.50');
    expect(screen.getByTestId('quote-pay')).toHaveTextContent('Pay NGN 12250.50');
  });

  it('says no tax has been applied rather than showing zero tax', async () => {
    await reachReview();

    expect(screen.getByTestId('quote-tax')).toHaveTextContent(/No tax has been applied/);
    expect(screen.getByTestId('quote-tax')).not.toHaveTextContent(/NGN 0\.00/);
  });

  it('refuses to offer payment where no live merchant account exists', async () => {
    mockedMethods.mockResolvedValue(
      methods({
        collection_enabled: false,
        collection_blocked_reason: 'no live merchant account (D3/D4)',
      }),
    );

    await reachReview();
    await waitFor(() =>
      expect(screen.getByTestId('collection-blocked')).toBeTruthy(),
    );

    expect(screen.getByTestId('quote-pay')).toBeDisabled();
    expect(mockedCheckout).not.toHaveBeenCalled();
  });
});

describe('an expired price is re-priced, not failed (AC-37.4)', () => {
  it('shows the expired state instead of a countdown when the quote has lapsed', async () => {
    mockedQuote.mockResolvedValue(
      quote({ expires_at: new Date(Date.now() - 1000).toISOString() }),
    );

    await renderFlow();
    await press(`plan-${PRODUCT_ID}-choose`);

    // Straight to the expired state: `reachReview` waits for the review screen,
    // and the point here is that a lapsed quote never renders one.
    await waitFor(() => expect(screen.getByTestId('quote-expired')).toBeTruthy());
    expect(screen.queryByTestId('quote-pay')).toBeNull();
  });

  it('turns the server refusing an expired quote into a fresh price, not an error', async () => {
    mockedCheckout.mockRejectedValue(
      new ApiError('quote_expired', 'That price has expired.', 410),
    );

    await reachReview();
    await press('quote-pay');

    await waitFor(() => expect(screen.getByTestId('quote-expired')).toBeTruthy());
    expect(screen.queryByTestId('quote-error')).toBeNull();

    mockedCheckout.mockResolvedValue({
      outcome: 'awaiting_processor',
      order: order(),
      redirect_url: null,
      processor_reference: null,
      resumed: false,
    });
    mockedQuote.mockResolvedValue(quote({ quote_id: 'fresh-quote' }));
    await press('quote-expired-action');

    await waitFor(() => expect(screen.getByTestId('quote-review')).toBeTruthy());
    expect(mockedQuote).toHaveBeenCalledTimes(2);
  });
});

describe('twice means once (AC-37.5)', () => {
  it('sends one checkout for a double tap on pay', async () => {
    let resolveCheckout: (value: checkoutClient.CheckoutResponse) => void = () => {};
    mockedCheckout.mockImplementation(
      () =>
        new Promise<checkoutClient.CheckoutResponse>(resolve => {
          resolveCheckout = resolve;
        }),
    );

    await reachReview();

    // Both presses in one act, which is what a real double tap is: the second
    // arrives before React has re-rendered with the button disabled.
    await act(async () => {
      fireEvent.press(screen.getByTestId('quote-pay'));
      fireEvent.press(screen.getByTestId('quote-pay'));
    });

    expect(mockedCheckout).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveCheckout({
        outcome: 'awaiting_processor',
        order: order(),
        redirect_url: null,
        processor_reference: null,
        resumed: false,
      });
    });
  });

  it('resumes the existing order rather than buying again after a lost response', async () => {
    mockedCheckout.mockResolvedValue({
      outcome: 'already_paid',
      order: order({ payment_state: 'paid', fulfilment_state: 'requested' }),
      redirect_url: null,
      processor_reference: null,
      resumed: true,
    });
    mockedOrder.mockResolvedValue(
      order({ payment_state: 'paid', fulfilment_state: 'requested' }),
    );

    await reachReview();
    await press('quote-pay');

    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());
    expect(screen.getByTestId('order-provisioning')).toBeTruthy();
    expect(screen.queryByTestId('quote-pay')).toBeNull();
    expect(mockedCheckout).toHaveBeenCalledWith('token', QUOTE_ID);
  });
});

describe('leaving for the processor and coming back (AC-37.5)', () => {
  it('writes the order down before opening the payment page', async () => {
    mockedCheckout.mockResolvedValue({
      outcome: 'pay',
      order: order(),
      redirect_url: 'https://processor.test/session/abc123?token=secret',
      processor_reference: 'ps_1',
      resumed: false,
    });

    await reachReview();
    await press('quote-pay');

    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());
    expect(Linking.openURL).toHaveBeenCalledWith(
      'https://processor.test/session/abc123?token=secret',
    );

    const stored = JSON.parse(
      (await AsyncStorage.getItem(PENDING_ORDER_KEY)) ?? 'null',
    );
    expect(stored).toMatchObject({
      orderId: ORDER_ID,
      quoteId: QUOTE_ID,
      paymentStarted: true,
    });
  });

  it('never keeps the payment link on disk', async () => {
    mockedCheckout.mockResolvedValue({
      outcome: 'pay',
      order: order(),
      redirect_url: 'https://processor.test/session/abc123?token=secret',
      processor_reference: 'ps_1',
      resumed: false,
    });

    await reachReview();
    await press('quote-pay');
    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());

    const raw = (await AsyncStorage.getItem(PENDING_ORDER_KEY)) ?? '';
    expect(raw).not.toContain('processor.test');
    expect(raw).not.toContain('secret');
  });

  it('opens the order, not the catalog, when the app restarts after paying', async () => {
    mockedCheckout.mockResolvedValue({
      outcome: 'pay',
      order: order(),
      redirect_url: 'https://processor.test/session/abc',
      processor_reference: 'ps_1',
      resumed: false,
    });

    await reachReview();
    await press('quote-pay');
    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());

    // The app is killed on the way back from the processor.
    await cleanup();
    jest.clearAllMocks();
    mockedCompatibility.mockResolvedValue({
      platform: 'android',
      deviceModel: 'Pixel 8',
      osVersion: '14',
      supported: true,
    });
    mockedOrder.mockResolvedValue(
      order({ payment_state: 'paid', fulfilment_state: 'requested' }),
    );

    await renderFlow();

    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());
    expect(mockedOrder).toHaveBeenCalledWith('token', ORDER_ID);
    expect(mockedMarkets).not.toHaveBeenCalled();
    expect(screen.queryByTestId('plan-list')).toBeNull();
  });

  it('says it is confirming, not that payment is due, while a webhook is late', async () => {
    mockedCheckout.mockResolvedValue({
      outcome: 'pay',
      order: order(),
      redirect_url: 'https://processor.test/session/abc',
      processor_reference: 'ps_1',
      resumed: false,
    });
    // The processor took the money; nothing has told us yet.
    mockedOrder.mockResolvedValue(order({ payment_state: 'unpaid' }));

    await reachReview();
    await press('quote-pay');
    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());

    expect(screen.getByTestId('order-confirming')).toBeTruthy();
    expect(screen.getByTestId('order-confirming-body')).toHaveTextContent(/Don't pay again/);
    expect(screen.queryByTestId('order-unpaid')).toBeNull();
  });
});

describe('a paid order leads to its status, never to another purchase (AC-37.5)', () => {
  it('shows provisioning progress for a paid but unprovisioned order', async () => {
    await AsyncStorage.setItem(
      PENDING_ORDER_KEY,
      JSON.stringify({
        orderId: ORDER_ID,
        quoteId: QUOTE_ID,
        reference: 'OR-DEADBEEF',
        paymentStarted: true,
        savedAt: new Date().toISOString(),
      }),
    );
    mockedOrder.mockResolvedValue(
      order({ payment_state: 'paid', fulfilment_state: 'requested' }),
    );

    await renderFlow();

    expect(screen.getByTestId('order-provisioning')).toBeTruthy();
    expect(screen.queryByTestId('plan-list')).toBeNull();
    expect(screen.queryByTestId('order-unpaid')).toBeNull();
    expect(screen.queryByTestId('order-declined')).toBeNull();
  });

  it('does not invite a retry for a supplier outcome we are still reconciling', async () => {
    await AsyncStorage.setItem(
      PENDING_ORDER_KEY,
      JSON.stringify({
        orderId: ORDER_ID,
        quoteId: QUOTE_ID,
        reference: 'OR-DEADBEEF',
        paymentStarted: true,
      }),
    );
    mockedOrder.mockResolvedValue(
      order({
        payment_state: 'paid',
        fulfilment_state: 'outcome_unknown',
        items: [
          {
            order_item_id: 'item-1',
            product_id: PRODUCT_ID,
            product_name: 'Nigeria 5GB',
            unit_currency: 'NGN',
            unit_amount: '12000.00',
            provisioning_state: 'outcome_unknown',
            recipient_user_id: null,
          },
        ],
      }),
    );

    await renderFlow();

    expect(screen.getByTestId('order-unknown')).toHaveTextContent(/checking the original request/);
    expect(screen.getByTestId('order-unknown-action')).toHaveTextContent(/Check again/);
  });

  it('stops forcing the status screen once the order is finished', async () => {
    await AsyncStorage.setItem(
      PENDING_ORDER_KEY,
      JSON.stringify({
        orderId: ORDER_ID,
        quoteId: QUOTE_ID,
        reference: 'OR-DEADBEEF',
        paymentStarted: true,
      }),
    );
    mockedOrder.mockResolvedValue(
      order({ payment_state: 'paid', fulfilment_state: 'provisioned' }),
    );

    await renderFlow();

    expect(screen.getByTestId('order-ready')).toBeTruthy();
    await waitFor(async () =>
      expect(await AsyncStorage.getItem(PENDING_ORDER_KEY)).toBeNull(),
    );
  });
});

describe('a declined payment keeps the order (AC-37.5)', () => {
  it('offers to pay the same order again, with the same quote', async () => {
    await AsyncStorage.setItem(
      PENDING_ORDER_KEY,
      JSON.stringify({
        orderId: ORDER_ID,
        quoteId: QUOTE_ID,
        reference: 'OR-DEADBEEF',
        paymentStarted: true,
      }),
    );
    mockedOrder.mockResolvedValue(order({ payment_state: 'failed' }));
    mockedCheckout.mockResolvedValue({
      outcome: 'pay',
      order: order(),
      redirect_url: 'https://processor.test/session/retry',
      processor_reference: 'ps_2',
      resumed: true,
    });

    await renderFlow();

    expect(screen.getByTestId('order-declined')).toHaveTextContent(/Nothing has been charged/);

    await press('order-declined-action');

    // The same quote id: a fresh one would be a second order for the same
    // basket, which is the duplicate this whole flow exists to prevent.
    expect(mockedCheckout).toHaveBeenCalledWith('token', QUOTE_ID);
    expect(mockedQuote).not.toHaveBeenCalled();
  });
});

describe('opening a named order (AC-37.3, AC-37.5)', () => {
  it('opens the order a deep link or Home asked for', async () => {
    mockedOrder.mockResolvedValue(
      order({ payment_state: 'paid', fulfilment_state: 'provisioned' }),
    );

    await renderFlow({ initialOrderId: ORDER_ID });

    await waitFor(() => expect(screen.getByTestId('order-status')).toBeTruthy());
    expect(mockedOrder).toHaveBeenCalledWith('token', ORDER_ID);
  });

  it('explains an order it cannot open instead of showing a blank screen', async () => {
    mockedOrder.mockRejectedValue(
      new ApiError('order_not_found', 'We could not find that order.', 404),
    );

    await renderFlow({ initialOrderId: ORDER_ID });

    await waitFor(() =>
      expect(screen.getByTestId('order-loading-state')).toHaveTextContent(/could not find that order/),
    );
    expect(screen.getByTestId('order-loading-state-action')).toBeTruthy();
  });
});

describe('nothing on sale is an answer, not an outage', () => {
  it('says so plainly when no market is published', async () => {
    mockedMarkets.mockResolvedValue({ markets: [] });

    await renderFlow();

    expect(screen.getByTestId('plans-no-market')).toHaveTextContent(/aren't selling in any country yet/);
    expect(mockedProducts).not.toHaveBeenCalled();
  });
});
