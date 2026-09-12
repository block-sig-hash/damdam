import { apiRequest } from './http';

/**
 * Mirrors apps/api/app/checkout/schemas.py (US-37, chunk 19).
 *
 * Every amount is a **string**, and that is not an oversight to be tidied up by
 * a `Number()` at the edge. A price that crosses JSON as a float can come back a
 * hundredth different from the one that was shown, and the one thing a quote
 * must be is exactly what the customer agreed to. The app formats these; it
 * never arithmetics them.
 */

export interface MarketSummary {
  country: string;
  currency: string;
  seller_name: string;
}

export interface MarketListResponse {
  markets: MarketSummary[];
}

export interface CallDestination {
  country: string;
  destination_kind: string;
  per_minute_amount: string;
  setup_amount: string;
  increment_seconds: number;
}

export interface ProductSummary {
  product_id: string;
  sku: string;
  name: string;
  kind: string;
  currency: string;
  amount: string;
  data_bytes: number;
  voice_seconds: number;
  validity_days: number | null;
  requires_esim: boolean;
  requires_unlocked_device: boolean;
  device_notes: string | null;
  number_type: string;
  number_country: string | null;
  number_assignment: string;
  coverage_countries: string[];
  call_destinations: CallDestination[];
  tariff_version: number | null;
  /** False with a reason. The card is still rendered; see PlanListScreen. */
  purchasable: boolean;
  unavailable_reason: string | null;
}

export interface ProductListResponse {
  country: string;
  currency: string;
  products: ProductSummary[];
}

/**
 * What the handset could actually be asked.
 *
 * `null` means **not checked** and is deliberately distinct from `false`,
 * "checked and incapable". The app may only ever report an observation, so a
 * carrier lock — which no public API exposes on either platform — stays `null`
 * forever and the customer is given guidance instead of a verdict.
 */
export interface DeviceFactsRequest {
  supports_esim: boolean | null;
  is_unlocked: boolean | null;
}

export interface QuoteLineRequest {
  product_id: string;
  quantity: number;
  recipient_user_id?: string | null;
}

export interface QuoteItemResponse {
  product_id: string;
  product_name: string;
  quantity: number;
  unit_amount: string;
  line_amount: string;
  recipient_user_id: string | null;
}

export interface QuoteResponse {
  quote_id: string;
  reference: string;
  status: string;
  currency: string;
  subtotal_amount: string;
  tax_amount: string;
  fee_amount: string;
  total_amount: string;
  /** Null until D3 records an entity and a tax treatment — not "zero tax". */
  tax_configuration_reference: string | null;
  seller_name: string;
  issued_at: string;
  expires_at: string;
  items: QuoteItemResponse[];
}

export interface WalletOption {
  wallet: string;
  available: boolean;
  reason: string | null;
}

export interface PaymentMethodsResponse {
  methods: string[];
  wallets: WalletOption[];
  card_fallback_required: boolean;
  collection_enabled: boolean;
  collection_blocked_reason: string | null;
}

export interface OrderItemResponse {
  order_item_id: string;
  product_id: string;
  product_name: string;
  unit_currency: string;
  unit_amount: string;
  provisioning_state: string;
  recipient_user_id: string | null;
}

export type PaymentState =
  | 'unpaid'
  | 'authorized'
  | 'paid'
  | 'refunded'
  | 'failed';

export type ProvisioningState =
  | 'not_started'
  | 'requested'
  | 'outcome_unknown'
  | 'provisioned'
  | 'failed'
  | 'cancelled';

export interface OrderResponse {
  order_id: string;
  quote_id: string | null;
  reference: string;
  currency: string;
  total_amount: string;
  payment_state: PaymentState;
  payment_attempt_state:
    | 'created'
    | 'pending'
    | 'succeeded'
    | 'failed'
    | 'unknown'
    | 'abandoned'
    | null;
  placed_at: string;
  items: OrderItemResponse[];
  fulfilment_state: ProvisioningState;
}

export interface OrderListResponse {
  orders: OrderResponse[];
}

/** Decided by the server, never re-derived here. See CheckoutOutcome. */
export type CheckoutOutcome = 'pay' | 'already_paid' | 'awaiting_processor';

export interface CheckoutResponse {
  outcome: CheckoutOutcome;
  order: OrderResponse;
  redirect_url: string | null;
  processor_reference: string | null;
  /** True when the server returned an order that already existed. */
  resumed: boolean;
}

export function listMarkets(): Promise<MarketListResponse> {
  return apiRequest<MarketListResponse>('/catalog/markets');
}

export function listProducts(
  country: string,
  currency: string,
  device: DeviceFactsRequest,
): Promise<ProductListResponse> {
  const query = new URLSearchParams({ country, currency });
  // Omitted, not sent as false: the server's tri-state is the whole reason the
  // "we could not check" case shows guidance rather than a refusal, and
  // `supports_esim=false` on the wire would collapse it into a verdict.
  if (device.supports_esim !== null) {
    query.set('supports_esim', String(device.supports_esim));
  }
  if (device.is_unlocked !== null) {
    query.set('is_unlocked', String(device.is_unlocked));
  }
  return apiRequest<ProductListResponse>(`/catalog/products?${query.toString()}`);
}

export function createQuote(
  accessToken: string,
  body: {
    country: string;
    currency: string;
    lines: QuoteLineRequest[];
    device: DeviceFactsRequest;
  },
): Promise<QuoteResponse> {
  return apiRequest<QuoteResponse>('/quotes', {
    method: 'POST',
    accessToken,
    body: {
      ...body,
      device: {
        supports_esim: body.device.supports_esim,
        is_unlocked: body.device.is_unlocked,
      },
    },
  });
}

export function getQuote(
  accessToken: string,
  quoteId: string,
): Promise<QuoteResponse> {
  return apiRequest<QuoteResponse>(`/quotes/${quoteId}`, { accessToken });
}

export function getPaymentMethods(
  accessToken: string,
  params: {
    country: string;
    currency: string;
    deviceOffersApplePay?: boolean;
    deviceOffersGooglePay?: boolean;
  },
): Promise<PaymentMethodsResponse> {
  const query = new URLSearchParams({
    country: params.country,
    currency: params.currency,
    device_offers_apple_pay: String(params.deviceOffersApplePay ?? false),
    device_offers_google_pay: String(params.deviceOffersGooglePay ?? false),
  });
  return apiRequest<PaymentMethodsResponse>(`/checkout/methods?${query}`, {
    accessToken,
  });
}

/**
 * Buy the basket this quote priced.
 *
 * Safe to call twice, and the app relies on that: the quote is the server's
 * idempotency key, so a double tap, a retry after a lost response and a
 * cold-started app all resolve to the same order with `resumed: true`. There is
 * deliberately no client-generated `Idempotency-Key` here — a second, weaker key
 * layered over a strong one only gets a chance to disagree with it.
 */
export function placeCheckout(
  accessToken: string,
  quoteId: string,
  method: string = 'card',
): Promise<CheckoutResponse> {
  return apiRequest<CheckoutResponse>('/checkout', {
    method: 'POST',
    accessToken,
    body: { quote_id: quoteId, method },
  });
}

export function getOrder(
  accessToken: string,
  orderId: string,
): Promise<OrderResponse> {
  return apiRequest<OrderResponse>(`/me/orders/${orderId}`, { accessToken });
}

export function listOrders(accessToken: string): Promise<OrderListResponse> {
  return apiRequest<OrderListResponse>('/me/orders', { accessToken });
}

/**
 * Whether this order still needs the customer to do something about money.
 *
 * Not `payment_state !== 'paid'`: an order the processor has accepted but whose
 * webhook has not landed is `unpaid` too, and asking that customer to pay again
 * is exactly the double charge AC-37.5 exists to prevent. The caller pairs this
 * with what it knows locally about whether a payment was actually started.
 */
export function awaitsPayment(order: OrderResponse): boolean {
  return order.payment_state === 'unpaid' || order.payment_state === 'failed';
}
