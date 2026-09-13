/**
 * Canned data for the screenshot harness (screenshotHarness/README.md).
 * None of this is real user data -- it exists only to give network- or
 * storage-dependent screens something to render without a live API.
 */
import type { PricingTier } from '../src/api/pricingClient';
import type { EsimProfile } from '../src/api/esimClient';
import type { ActivationRedemption } from '../src/api/activationClient';
import type {
  MarketSummary,
  OrderResponse,
  PaymentMethodsResponse,
  ProductSummary,
  QuoteResponse,
} from '../src/api/checkoutClient';
import type { DeviceCheck } from '../src/screens/Purchase/deviceFacts';
import type {
  InstallationCredential,
  LineDetail,
} from '../src/api/lineClient';

// 1x1 transparent PNG -- stands in for a real QR code image URL so
// <Image> has something to decode without a network round-trip.
export const PLACEHOLDER_IMAGE_DATA_URI =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

export const FIXTURE_PHONE_NUMBER = '+2348012345678';
export const FIXTURE_ACCESS_TOKEN = 'harness-fixture-access-token';
export const FIXTURE_PACKAGE_ID = 'harness-fixture-package-id';

export const FIXTURE_PRICING_TIERS: PricingTier[] = [
  { id: 'tier-starter', name: 'Starter', ngn_price: 15000, data_gb: 5, pstn_minutes: 30, is_group_tier: false },
  { id: 'tier-basic', name: 'Basic', ngn_price: 25000, data_gb: 10, pstn_minutes: 60, is_group_tier: false },
  { id: 'tier-standard', name: 'Standard', ngn_price: 40000, data_gb: 20, pstn_minutes: 120, is_group_tier: false },
  {
    id: 'tier-family',
    name: 'Family',
    ngn_price: 18000,
    data_gb: 10,
    pstn_minutes: 60,
    is_group_tier: true,
    min_group_size: 2,
    max_group_size: 8,
  },
];

export const FIXTURE_ESIM_PROFILE: EsimProfile = {
  esim_profile_id: 'harness-esim-profile',
  iccid: '8923410123456789012',
  activation_code_lpa: 'LPA:1$rsp.example.com$HARNESS-ACTIVATION-CODE',
  qr_code_url: PLACEHOLDER_IMAGE_DATA_URI,
  status: 'issued',
  downloaded_at: null,
  activated_at: null,
};

export const FIXTURE_ACTIVATION_REDEMPTION: ActivationRedemption = {
  package_id: FIXTURE_PACKAGE_ID,
  pricing_tier_name: 'Standard',
  data_gb_total: 20,
  pstn_minutes_total: 120,
  status: 'active',
};


/**
 * Chunk 19's purchase journey (US-37).
 *
 * The amounts are strings because the API sends strings — see
 * `src/api/checkoutClient.ts`. A fixture that used numbers here would render a
 * screen the real one cannot produce, and the whole point of a screenshot is
 * that it is the real screen.
 */
export const FIXTURE_MARKET: MarketSummary = {
  country: 'NG',
  currency: 'NGN',
  seller_name: 'DamDam Ltd',
};

export const FIXTURE_PRODUCT: ProductSummary = {
  product_id: 'harness-product-bundle',
  sku: 'NG-BUNDLE-5GB',
  name: 'Nigeria 5GB + calls',
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
};

/** The same plan on a handset the eSIM check could not confirm. */
export const FIXTURE_PRODUCT_DEVICE_BLOCKED: ProductSummary = {
  ...FIXTURE_PRODUCT,
  purchasable: false,
  unavailable_reason: 'device_not_esim_capable',
};

export const FIXTURE_DEVICE_CHECKED: DeviceCheck = {
  facts: { supports_esim: true, is_unlocked: null },
  source: 'device',
  model: 'Pixel 8',
  reportedIncapable: false,
};

export const FIXTURE_DEVICE_INCAPABLE: DeviceCheck = {
  facts: { supports_esim: false, is_unlocked: null },
  source: 'device',
  model: 'iPhone 8',
  reportedIncapable: true,
};

export const FIXTURE_QUOTE: QuoteResponse = {
  quote_id: 'harness-quote',
  reference: 'QT-HARNESS',
  status: 'issued',
  currency: 'NGN',
  subtotal_amount: '12000.00',
  tax_amount: '0.00',
  fee_amount: '0.00',
  total_amount: '12000.00',
  // Null, not "0.00": D3 has not recorded an entity or a tax treatment, and the
  // review screen says so in words rather than showing zero tax.
  tax_configuration_reference: null,
  seller_name: 'DamDam Ltd',
  issued_at: '2026-09-11T10:00:00Z',
  expires_at: '2026-09-11T10:15:00Z',
  items: [
    {
      product_id: FIXTURE_PRODUCT.product_id,
      product_name: FIXTURE_PRODUCT.name,
      quantity: 1,
      unit_amount: '12000.00',
      line_amount: '12000.00',
      recipient_user_id: null,
    },
  ],
};

/** Return an active quote whose visible countdown is stable at 15 minutes. */
export function createActiveFixtureQuote(now = Date.now()): QuoteResponse {
  return {
    ...FIXTURE_QUOTE,
    expires_at: new Date(now + 15 * 60 * 1000).toISOString(),
  };
}

export const FIXTURE_PAYMENT_METHODS: PaymentMethodsResponse = {
  methods: ['card', 'bank_transfer'],
  wallets: [
    { wallet: 'apple_pay', available: false, reason: 'no_processor_selected' },
    { wallet: 'google_pay', available: false, reason: 'no_processor_selected' },
  ],
  card_fallback_required: true,
  collection_enabled: true,
  collection_blocked_reason: null,
};

/** The state every real deployment is in today: D3/D4 open, no live account. */
export const FIXTURE_PAYMENT_METHODS_BLOCKED: PaymentMethodsResponse = {
  ...FIXTURE_PAYMENT_METHODS,
  collection_enabled: false,
  collection_blocked_reason:
    'no live merchant account for this seller and currency (DECISIONS.md D3/D4)',
};

export const FIXTURE_ORDER: OrderResponse = {
  order_id: 'harness-order',
  quote_id: 'harness-quote',
  reference: 'OR-HARNESS1',
  currency: 'NGN',
  total_amount: '12000.00',
  payment_state: 'paid',
  payment_attempt_state: 'succeeded',
  placed_at: '2026-09-11T10:05:00Z',
  items: [
    {
      order_item_id: 'harness-order-item',
      product_id: FIXTURE_PRODUCT.product_id,
      product_name: FIXTURE_PRODUCT.name,
      unit_currency: 'NGN',
      unit_amount: '12000.00',
      provisioning_state: 'requested',
      recipient_user_id: null,
    },
  ],
  fulfilment_state: 'requested',
};

export const FIXTURE_ORDER_DECLINED: OrderResponse = {
  ...FIXTURE_ORDER,
  payment_state: 'failed',
  payment_attempt_state: 'failed',
  items: FIXTURE_ORDER.items.map(item => ({
    ...item,
    provisioning_state: 'not_started',
  })),
  fulfilment_state: 'not_started',
};

/** Paid at the processor; the webhook has not landed. */
export const FIXTURE_ORDER_AWAITING_WEBHOOK: OrderResponse = {
  ...FIXTURE_ORDER_DECLINED,
  payment_state: 'unpaid',
  payment_attempt_state: 'pending',
};

/**
 * Chunk 20's My Line and installation screens (US-38).
 *
 * The activation code below is deliberately unusable: `.invalid` is a reserved
 * TLD that can never resolve, and the matching id says what it is. A harness
 * fixture that looked like a real LPA would be activation material living in the
 * repository, which is the one thing `security.md` is unambiguous about.
 */
export const FIXTURE_HARNESS_LPA =
  'LPA:1$harness.invalid$HARNESS-PLACEHOLDER-NOT-A-REAL-PROFILE';

export const FIXTURE_LINE: LineDetail = {
  entitlement_id: 'harness-entitlement',
  order_id: 'harness-order',
  order_reference: 'OR-HARNESS1',
  order_item_id: 'harness-order-item',
  product_id: 'harness-product',
  product_name: 'Nigeria 5GB + calls',
  delivery: 'carrier_esim',
  ready_to_use: true,
  number_status: 'assigned',
  assigned_number: {
    e164: '+2349012345678',
    country: 'NG',
    assigned_at: '2026-09-12T09:00:00Z',
  },
  installation: {
    state: 'installed',
    installed_at: '2026-09-12T09:20:00Z',
    profile_released_at: '2026-09-12T09:10:00Z',
    credential_available: true,
    credential_unavailable_reason: null,
    delivery_count: 1,
    one_time_use: true,
    reinstall_available: false,
    reinstall_blocked_reason: 'one_time_profile',
  },
  line: {
    carrier: 'telnyx',
    activation_state: 'active',
    network_state: 'attached',
    network_state_observed_at: '2026-09-12T09:25:00Z',
    provider_status: 'active',
    provider_status_observed_at: '2026-09-12T09:25:00Z',
    voice_enabled: true,
    voice_enabled_observed_at: '2026-09-12T09:25:00Z',
  },
  usage: {
    data_bytes_total: 5 * 1024 * 1024 * 1024,
    data_bytes_used: 1024 * 1024 * 1024,
    data_bytes_remaining: 4 * 1024 * 1024 * 1024,
    voice_seconds_total: 3600,
    voice_seconds_used: 600,
    voice_seconds_remaining: 3000,
    // Fixed rather than relative: a screenshot whose "updated N min ago" line
    // changes between runs is a screenshot that can never be compared.
    observed_at: '2026-09-12T09:25:00Z',
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
};

/** Installed on the phone, and the carrier has not switched the line on. */
export const FIXTURE_LINE_AWAITING_ACTIVATION: LineDetail = {
  ...FIXTURE_LINE,
  ready_to_use: false,
  line: {
    ...FIXTURE_LINE.line!,
    activation_state: 'pending',
    network_state: 'unknown',
    network_state_observed_at: null,
  },
  calling: {
    ...FIXTURE_LINE.calling,
    native_available: false,
    native_unavailable_reason: 'line_not_active',
  },
};

export const FIXTURE_LINE_SUSPENDED: LineDetail = {
  ...FIXTURE_LINE,
  ready_to_use: false,
  line: { ...FIXTURE_LINE.line!, activation_state: 'suspended' },
  restriction: {
    ...FIXTURE_LINE.restriction!,
    suspended: true,
    detail: 'allowance exhausted',
  },
};

/** Nobody has ever measured this line, which the meter must not hide. */
export const FIXTURE_LINE_UNMEASURED: LineDetail = {
  ...FIXTURE_LINE,
  usage: {
    ...FIXTURE_LINE.usage,
    data_bytes_used: 0,
    data_bytes_remaining: 5 * 1024 * 1024 * 1024,
    voice_seconds_used: 0,
    voice_seconds_remaining: 3600,
    observed_at: null,
    freshness: 'unknown',
  },
};

export const FIXTURE_INSTALLATION_CREDENTIAL: InstallationCredential = {
  entitlement_id: FIXTURE_LINE.entitlement_id,
  lpa: FIXTURE_HARNESS_LPA,
  one_time_use: true,
  delivery_count: 1,
  reinstall_available: false,
};
