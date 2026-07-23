# Multi-Currency and Billing-Country Architecture Scoping
# DamDam — Version 0.1 · Audit date: 23 July 2026

## 1. Decision summary

This report builds on
[`payment-termii-scoping.md`](./payment-termii-scoping.md). It does not
repeat the provider-country research.

The current payment domain is not merely configured for NGN; NGN is encoded
through the database, service contracts, webhook validation, pricing APIs,
invoice/receipt rendering, mobile UI, dashboard UI, and test fixtures.
The exact audit found:

| Surface | Files coupled to NGN |
|---|---:|
| API runtime | 12 |
| Existing schema migrations | 3 |
| Dashboard runtime | 4 |
| Mobile runtime | 2 |
| Mobile screenshot harness | 1 |
| Test files requiring migration | 27 |
| Source-of-truth/specification documents | 9 |

The 22 non-test source files are inventoried in §2 with exact line
references. Historical migration files should remain unchanged; they are
listed because they establish the backfill state a new migration must
handle.

There is no billing-country model today. The authenticated user's phone is
Nigerian-only, the HTO organization is NAHCON/Nigeria-shaped, invoices point
to one globally configured Nigerian bank account, and processor
initialization sends only email plus NGN amount. The system stores neither
claimed billing country nor provider-observed card/wallet country. It has no
BVN/KYC, BIN/issuer-country, AVS, 3DS, payment-IP, or application-level
payment-fraud logic.

The recommended foundation is:

1. keep `destination_country` exclusively as the trip/product dimension;
2. introduce `market_country` as the server-authorized sale-market and
   price-book dimension;
3. snapshot `billing_country`, `amount`, and `currency` on every financial
   record;
4. use native market quotes rather than runtime FX conversion for the first
   expansion;
5. introduce payment attempts beneath the transaction so an ordered
   per-country processor cascade is auditable; and
6. normalize mobile money as a payment method plus a separately retained
   network, without storing wallet credentials or full raw provider payloads.

The earlier **8–15 engineering-day** estimate remains reasonable: 5–8 days
for the market-independent foundation and 3–7 days for the first enabled
Francophone mobile-money market. Provider onboarding and live certification
are external elapsed time.

## 2. Exact NGN inventory

### 2.1 Counting and scope

The audit searched production Python/TypeScript/TSX, current Alembic
migrations, the screenshot harness, tests, API contracts, and product/
architecture documents. Generated dependency lockfiles and unrelated
Nigeria references such as voice routing or product positioning were
excluded from the currency count.

A file is counted once even if it contains several NGN assumptions. The
table below gives every current non-test source file and all material line
groups; the surrounding description distinguishes schema, arithmetic,
provider, and display coupling.

### 2.2 API runtime — 12 files

| File and exact lines | NGN-specific behavior |
|---|---|
| [`app/auth/models.py:393`](../apps/api/app/auth/models.py#L393), [`:418–419`](../apps/api/app/auth/models.py#L418), [`:431`](../apps/api/app/auth/models.py#L431), [`:452–455`](../apps/api/app/auth/models.py#L452) | `PricingTier.ngn_price`, NGN-only price-change history, and `ManifestOrder.wholesale_price_ngn`/`total_ngn`; the database check constraint names those columns |
| [`app/packages/models.py:162`](../apps/api/app/packages/models.py#L162) | `Transaction.amount_ngn` has no parallel currency |
| [`app/payments/providers.py:21–39`](../apps/api/app/payments/providers.py#L21), [`:81–90`](../apps/api/app/payments/providers.py#L81), [`:120–126`](../apps/api/app/payments/providers.py#L120), [`:144–158`](../apps/api/app/payments/providers.py#L144), [`:188–194`](../apps/api/app/payments/providers.py#L188) | Provider contracts call the value `amount_ngn`; Paystack always multiplies by 100 and sends NGN; both webhook parsers reject non-NGN; Flutterwave maps generic mobile money to Nigeria-only `opay` |
| [`app/payments/service.py:82`](../apps/api/app/payments/service.py#L82), [`:99–114`](../apps/api/app/payments/service.py#L99), [`:161`](../apps/api/app/payments/service.py#L161), [`:366–375`](../apps/api/app/payments/service.py#L366) | Retail price is read from `tier.ngn_price`, rounded unconditionally to 0.01, stored as `amount_ngn`, compared without a currency, and passed to receipt notifications as NGN |
| [`app/pricing/schemas.py:9–15`](../apps/api/app/pricing/schemas.py#L9) | Public retail response exposes `ngn_price` and `per_person_ngn_rate` |
| [`app/pricing/service.py:27–34`](../apps/api/app/pricing/service.py#L27) | Retail catalog reads the single NGN tier price and converts `Decimal` to JSON float |
| [`app/manifests/schemas.py:97–172`](../apps/api/app/manifests/schemas.py#L97) | HTO/admin DTOs expose retail, wholesale, margin, total, and price-change values with `_ngn` names, all as floats |
| [`app/manifests/orders.py:49`](../apps/api/app/manifests/orders.py#L49), [`:91–128`](../apps/api/app/manifests/orders.py#L91), [`:300–301`](../apps/api/app/manifests/orders.py#L300), [`:347–447`](../apps/api/app/manifests/orders.py#L347), [`:656–666`](../apps/api/app/manifests/orders.py#L656), [`:718–759`](../apps/api/app/manifests/orders.py#L718) | NGN price reads/updates, a global `Decimal("0.01")` money quantum, native order snapshots, float serialization, invoice/notification arguments, and wholesale calculation |
| [`app/manifests/invoices.py:92–109`](../apps/api/app/manifests/invoices.py#L92) | PDF data contract and rendered lines are named/formatted as `NGN …:,.2f` |
| [`app/admin/routes.py:305–337`](../apps/api/app/admin/routes.py#L305) | Admin pricing request/response and percentage-change path are tied to `ngn_price` fields |
| [`app/notifications/service.py:27–32`](../apps/api/app/notifications/service.py#L27), [`:55`](../apps/api/app/notifications/service.py#L55), [`:101–119`](../apps/api/app/notifications/service.py#L101) | Notification interfaces carry `total_ngn`/`amount_ngn`, preventing provider-neutral money rendering |
| [`app/notifications/providers.py:100–132`](../apps/api/app/notifications/providers.py#L100), [`:221–228`](../apps/api/app/notifications/providers.py#L221) | Invoice email, receipt email, and WhatsApp template parameters render `NGN` and always use two decimal places |

Two rounding assumptions are currently different: backend purchase/order
math quantizes to two decimal places, while dashboard formatting explicitly
hides all fractional digits (§2.4). Neither behavior is selected from the
currency.

The two USD fields on `PricingTier` are not an exchange-rate source.
[`app/manifests/orders.py:659–666`](../apps/api/app/manifests/orders.py#L659)
uses `wholesale_usd_price / usd_reference_price` as a wholesale discount
ratio against the manually configured NGN retail price. No current checkout
performs an FX lookup or records an FX rate.

### 2.3 Existing migrations — 3 files

| File and exact lines | Historical state |
|---|---|
| [`0006_us06_manifest_orders.py:62`](../apps/api/migrations/versions/0006_us06_manifest_orders.py#L62), [`:91–115`](../apps/api/migrations/versions/0006_us06_manifest_orders.py#L91) | Created tier NGN price and NGN manifest-order columns/check |
| [`0008_us26_manual_pricing.py:1–84`](../apps/api/migrations/versions/0008_us26_manual_pricing.py#L1) | Replaced the old price cache with mutable `ngn_price` and NGN price-change history |
| [`0010_us09_retail_payments.py:60`](../apps/api/migrations/versions/0010_us09_retail_payments.py#L60) | Created `transactions.amount_ngn` |

These migrations are immutable history. A new numbered migration must add
and backfill generic fields; it must not rewrite them.

### 2.4 Dashboard runtime — 4 files

| File and exact lines | NGN-specific behavior |
|---|---|
| [`admin/manifest-orders/page.tsx:12`](../apps/dashboard/app/admin/manifest-orders/page.tsx#L12), [`:65`](../apps/dashboard/app/admin/manifest-orders/page.tsx#L65) | Hardcoded `Intl.NumberFormat("en-NG", currency: "NGN", maximumFractionDigits: 0)` and `total_ngn` |
| [`admin/pricing-tiers/page.tsx:11–106`](../apps/dashboard/app/admin/pricing-tiers/page.tsx#L11) | Same formatter, NGN-only edit contract/calculation, “Naira pricing,” and `₦` input label |
| [`manifests/[id]/order/page.tsx:20–22`](../apps/dashboard/app/manifests/%5Bid%5D/order/page.tsx#L20), [`:88–89`](../apps/dashboard/app/manifests/%5Bid%5D/order/page.tsx#L88), [`:155`](../apps/dashboard/app/manifests/%5Bid%5D/order/page.tsx#L155), [`:227–255`](../apps/dashboard/app/manifests/%5Bid%5D/order/page.tsx#L227) | Hardcoded NGN formatter and NGN retail/wholesale/margin/total fields |
| [`lib/api.ts:173–185`](../apps/dashboard/lib/api.ts#L173), [`:247`](../apps/dashboard/lib/api.ts#L247), [`:361`](../apps/dashboard/lib/api.ts#L361), [`:391–419`](../apps/dashboard/lib/api.ts#L391) | Dashboard API types and admin update payload use `_ngn` fields |

### 2.5 Mobile runtime and harness — 3 files

| File and exact lines | NGN-specific behavior |
|---|---|
| [`src/api/pricingClient.ts:6–12`](../apps/mobile/src/api/pricingClient.ts#L6) | Mobile catalog contract exposes `ngn_price`/`per_person_ngn_rate` |
| [`PackageSelectionScreen.tsx:35–37`](../apps/mobile/src/screens/PackageSelection/PackageSelectionScreen.tsx#L35), [`:94`](../apps/mobile/src/screens/PackageSelection/PackageSelectionScreen.tsx#L94), [`:192–195`](../apps/mobile/src/screens/PackageSelection/PackageSelectionScreen.tsx#L192), [`:272`](../apps/mobile/src/screens/PackageSelection/PackageSelectionScreen.tsx#L272), [`:301`](../apps/mobile/src/screens/PackageSelection/PackageSelectionScreen.tsx#L301) | Hand-built `₦` formatter rounds to an integer, group total uses NGN field, and visible copy says Naira |
| [`screenshotHarness/fixtures.ts:22–28`](../apps/mobile/screenshotHarness/fixtures.ts#L22) | Screenshot fixtures implement the NGN-only catalog shape |

`RetailPurchaseFlow` does not render a currency amount, but its
[`line 186`](../apps/mobile/src/screens/RetailPurchase/RetailPurchaseFlow.tsx#L186)
advertises Nigerian card/bank transfer/USSD/OPay/PalmPay rails. It is part
of the market-specific checkout inventory in §3 rather than the literal
currency count.

### 2.6 Test and contract blast radius

Exactly **27 test files** contain NGN schema fields, fixtures, provider
payloads, or rendered Naira assertions: 21 API files, 3 dashboard files,
and 3 mobile files.

- Payment/pricing tests:
  [`test_payment_model_postgres.py`](../apps/api/tests/test_payment_model_postgres.py),
  [`test_payment_providers.py`](../apps/api/tests/test_payment_providers.py),
  [`test_retail_payment_api.py`](../apps/api/tests/test_retail_payment_api.py),
  [`test_retail_pricing_api.py`](../apps/api/tests/test_retail_pricing_api.py),
  and [`test_manifest_order_api.py`](../apps/api/tests/test_manifest_order_api.py).
- Other API fixtures requiring schema updates:
  `test_activation_api.py`, `test_activation_model_postgres.py`,
  `test_checkin_api.py`, `test_device_compatibility_api.py`,
  `test_esim_activation_api.py`, `test_esim_model_postgres.py`,
  `test_esim_profile_api.py`, `test_manifest_order_model_postgres.py`,
  `test_package_admin_api.py`, `test_package_chaining.py`,
  `test_package_geofence_api.py`, `test_provisioning_report_api.py`,
  `test_provisioning_report_performance_postgres.py`,
  `test_retention_postgres.py`, `test_voice_api.py`, and
  `test_voice_model_postgres.py`.
- Frontend tests:
  dashboard admin manifest-order/pricing and manifest order-page tests,
  plus mobile pricing-client, Package Selection, and Retail Purchase tests.

Nine source-of-truth/specification documents carry NGN assumptions:
`prd.md`, `data-model.md`, `api-spec.md`, generated `api-spec.yaml`,
`frontend-mobile.md`, `frontend-dashboard.md`, `corporate-structure.md`,
`infrastructure.md`, and `scaling-infrastructure.md`. The API contract
alone exposes `_ngn` fields at
[`api-spec.md:204–207`](./api-spec.md#L204),
[`467–495`](./api-spec.md#L467), and
[`641–660`](./api-spec.md#L641).

## 3. Billing-country and Nigeria-market inventory

### 3.1 There is no billing-country source of truth

- `User` has a Nigerian-format `phone_number` and
  [`destination_country`](../apps/api/app/auth/models.py#L104), but no
  residence, sale-market, or billing-country field.
- `Organization` has contact details and a NAHCON licence
  ([`auth/models.py:183–220`](../apps/api/app/auth/models.py#L183)), but no
  organization country or billing country.
- `PurchaseRequest` contains only `pricing_tier_id` and `group_size`
  ([`payments/schemas.py:7–9`](../apps/api/app/payments/schemas.py#L7)).
- `Transaction` stores no currency, billing country, payer country,
  provider-observed instrument country, network, or customer identifier
  ([`packages/models.py:121–190`](../apps/api/app/packages/models.py#L121)).
- `PaymentInitialization` sends email but no phone, address, country,
  network, IP, or device signal
  ([`payments/providers.py:18–25`](../apps/api/app/payments/providers.py#L18)).

`destination_country` is the country being travelled to and provisioned,
currently `SA`. It must not route a Nigerian, Ghanaian, or Senegalese
payment. Phone country is also not a reliable substitute: a Senegalese
resident can retain another number, and a Nigerian buyer can pay for
someone travelling from another market.

### 3.2 Where Nigeria is assumed

| Area | Exact references | Effect |
|---|---|---|
| Signup/recovery/HTO registration | [`auth/schemas.py:11–21`](../apps/api/app/auth/schemas.py#L11), [`:37`](../apps/api/app/auth/schemas.py#L37), [`:116`](../apps/api/app/auth/schemas.py#L116) | Accepts only Nigerian local mobile patterns and converts them to `+234` |
| Family contacts | [`profile/schemas.py:8–25`](../apps/api/app/profile/schemas.py#L8) | Reuses the Nigerian-only validator |
| Manifest pilgrims | [`manifests/service.py:16`](../apps/api/app/manifests/service.py#L16), [`:231–235`](../apps/api/app/manifests/service.py#L231) | Rejects non-Nigerian pilgrim numbers |
| Mobile identity UI | [`utils/phoneNumber.ts:2–22`](../apps/mobile/src/utils/phoneNumber.ts#L2), [`PhoneEntryScreen.tsx:38–52`](../apps/mobile/src/screens/PhoneEntry/PhoneEntryScreen.tsx#L38), [`usePhoneEntry.ts:35`](../apps/mobile/src/screens/PhoneEntry/usePhoneEntry.ts#L35) | Client validation/display assumes Nigerian local numbers |
| Dashboard HTO registration | [`register/page.tsx:96–102`](../apps/dashboard/app/register/page.tsx#L96) | Labels and example are Nigerian-only |
| Checkout rails | [`payments/service.py:37`](../apps/api/app/payments/service.py#L37), [`providers.py:85–90`](../apps/api/app/payments/providers.py#L85), [`:144–147`](../apps/api/app/payments/providers.py#L144), and [`RetailPurchaseFlow.tsx:186`](../apps/mobile/src/screens/RetailPurchase/RetailPurchaseFlow.tsx#L186) | One global list combines Nigeria-specific and generic rails; Flutterwave mobile money is OPay |
| HTO invoice settlement | [`config.py:112–114`](../apps/api/app/config.py#L112), [`manifests/invoices.py:108–113`](../apps/api/app/manifests/invoices.py#L108) | One global bank configuration defaults the account name to “DamDam Nigeria” |
| Processor policy | [`config.py:70–71`](../apps/api/app/config.py#L70), [`payments/service.py:299–309`](../apps/api/app/payments/service.py#L299) | One global Paystack→Flutterwave order applies to every buyer |

Nigeria-specific voice number validation and caller-ID behavior also exist,
but they are not payment/billing-country logic. They are a parallel market
expansion dependency, not a usable routing signal.

### 3.3 KYC, payer validation, and fraud findings

There is **no application code** containing BVN, KYC, billing address,
billing country, card BIN/issuer country, AVS, 3DS, or payer-country
handling. Paystack's Nigerian bank/BVN requirement appears only as
merchant onboarding/corporate architecture in
[`corporate-structure.md:35–90`](./corporate-structure.md#L35); DamDam does
not collect a pilgrim's BVN.

The hosted processors own card entry and cardholder authentication. DamDam
does not receive full card numbers, which is correct. Current webhook
acceptance verifies signature, event/status, processor reference, NGN, and
amount. It does not:

- require the webhook processor to equal the transaction's selected
  processor before updating it;
- compare a billing/market country;
- record or compare a provider-observed card/wallet country;
- evaluate IP-country or billing-country mismatch; or
- maintain an application payment-risk score.

Dashboard “risk” sorting is pilgrim safety/check-in risk and is unrelated
to payment fraud.

One adjacent integrity gap should be fixed during the foundation:
[`PaymentService.initialize`](../apps/api/app/payments/service.py#L73)
checks that the submitted tier exists and is active, but does not prove the
tier belongs to the user's `destination_country` or to an authorized
market quote. The new purchase contract should select a server-issued quote
and bind product destination, market, currency, unit amount, and group
rules atomically.

## 4. Proposed money and market model

### 4.1 Terminology

Use three separate country concepts:

| Field | Meaning | Trust/source |
|---|---|---|
| `destination_country` | Where the package/eSIM is used | Existing product selection; immutable package snapshot |
| `market_country` | DamDam sale market/entity/price book that is allowed to sell the quote | Server-authorized profile/organization/checkout context |
| `billing_country` | Customer-declared billing/wallet country used for the payment attempt | Submitted at checkout, validated against the selected market and provider capability |
| `instrument_country` | Provider-observed card issuer or wallet country, if returned | Post-initialization/webhook evidence; never trusted from the client |

The first three should be ISO 3166-1 alpha-2 uppercase values.
`instrument_country` remains nullable because mobile-money and hosted
checkout payloads differ.

For retail, add `users.market_country` only when signup/profile has a
trustworthy country-selection flow. For HTO sales, add
`organizations.market_country`. The transaction must still snapshot the
resolved market and billing countries: mutable account fields must not
rewrite financial history.

### 4.2 Currency representation

Use an ISO 4217 uppercase `currency` code and an exact decimal amount
internally. Recommended storage is `NUMERIC(18,3)` plus currency-aware
validation/quantization, which supports zero-, two-, and three-minor-unit
currencies without floating-point loss. API money values should be decimal
strings or `{amount, currency}` objects, not binary floats.

Centralize a `Money` value object/utility that:

- validates supported currencies;
- quantizes using that currency's minor-unit exponent;
- rejects excess precision instead of silently rounding provider events;
- converts to a processor's expected major/minor-unit representation; and
- formats through locale/currency-aware frontend utilities.

Do not model currency as a database enum; adding a country should not
require changing an enum type. Use `CHAR(3)`/`VARCHAR(3)`, uppercase check,
and an application allowlist/currency metadata table.

### 4.3 Native market price book

Do not perform runtime FX conversion for the initial expansion. Create a
native quote table, conceptually:

```text
pricing_tier_market_prices
  id
  pricing_tier_id
  market_country
  currency
  retail_unit_amount
  wholesale_unit_amount
  active
  effective_from
  updated_by
  updated_at
  UNIQUE (pricing_tier_id, market_country, effective/current version)
```

This separates product destination (`pricing_tiers.destination_country`)
from buyer market. Senegal/Côte d’Ivoire/Burkina Faso can share XOF while
still having different quotes, taxes, fees, or commercial entities.
Cameroon uses XAF; a shared currency must never imply a shared market rule.

Keep immutable price history either with effective-dated rows or a generic
`pricing_tier_price_changes` ledger containing market, currency, old/new
amounts, admin, and timestamp. Do not overwrite currency in place on an
existing quote.

If the business later chooses converted rather than native prices, add an
`fx_rate_snapshots` table with `base_currency`, `quote_currency`, exact
rate, provider/source, source timestamp, fetched timestamp, and immutable
ID. The price/transaction must retain `fx_rate_snapshot_id` plus source and
target amounts. Never reconstruct a historical charged price from today's
rate. This FX model is not needed for the first expansion and should not be
built speculatively.

### 4.4 Financial record fields

Recommended changes:

**`transactions`**

- rename/backfill `amount_ngn` → `amount`;
- add non-null `currency`, `market_country`, and `billing_country`;
- add nullable `instrument_country`;
- add `payment_method = mobile_money`;
- add nullable `payment_network` as a normalized string such as
  `mtn_momo`, `orange_money`, `wave`, `moov`, `mobicash`, or
  `vodafone_cash`;
- retain the winning `processor`/`processor_reference` as convenient
  canonical settlement fields; and
- replace long-term raw `webhook_payload` retention with a minimized,
  allowlisted verification snapshot or give raw payloads a much shorter
  separately enforced retention period.

**`packages`**

- add immutable `purchase_amount`, `purchase_currency`, and
  `market_country` snapshots for package UI/history while the package
  exists;
- keep `destination_country` unchanged and separate; and
- treat the transaction, not the package, as the six-year financial
  authority because packages can be deleted with the user.

**`manifest_orders`**

- rename/backfill `wholesale_price_ngn` → `wholesale_unit_amount`;
- rename/backfill `total_ngn` → `total_amount`;
- add non-null `currency`, `market_country`, and `billing_country`;
- snapshot the market-specific bank/payment instructions used for the
  invoice, or reference an immutable settlement-account version; and
- make invoice/notification rendering accept structured Money.

Today, admin confirmation updates only `ManifestOrder.status` and
`payment_confirmed_at`
([`manifests/orders.py:454–469`](../apps/api/app/manifests/orders.py#L454)).
It does not create the `Transaction` row for which
`transactions.manifest_order_id` was designed. The implementation should
either create an invoice-type transaction at confirmation or explicitly
give manifest orders and invoice artifacts their own financial retention
rule. Leaving the field unused would make retail and HTO payments follow
different audit models.

Whether old `_ngn` columns are renamed in place or dual-written during a
compatibility window is an implementation/release choice. Because mobile
and dashboard deploy separately, a short additive phase is safer:
backfill generic fields to `NG`/`NGN`, write both shapes, migrate clients,
then remove legacy fields in a later migration.

## 5. Per-country processor cascade

### 5.1 Ordered policy

Replace the two global settings with a validated ordered map:

```text
NG -> [paystack, flutterwave]
GH -> [paystack, flutterwave]
BF, CM, CI, SN -> [flutterwave, paystack]
ML, NE, GN -> disabled until collection support is confirmed
```

Add a provider capability matrix for `(processor, market_country,
currency, payment_method, network)`. The priority resolver first selects
the market policy, then removes providers that cannot service the exact
quote/method. Unknown markets must fail closed; they must not inherit NG.

### 5.2 Preserve and harden cascade semantics

The current cascade changes processor only when checkout initialization
raises an error. Preserve that behavior: do not switch processors merely
because the customer later abandons or declines a checkout.

For an auditable cascade, add `payment_attempts`:

```text
payment_attempts
  id
  transaction_id
  processor
  processor_reference
  priority_position
  status                # initializing, initialized, failed, succeeded
  failure_code
  payment_method
  payment_network
  instrument_country
  initialized_at
  completed_at
  UNIQUE (processor, processor_reference)
```

Create the parent transaction and immutable quote snapshot before the
first provider call. Record each initialization attempt. Return the first
successful checkout/next action. Webhooks resolve by **processor plus
reference**, lock the parent transaction, compare exact amount and currency,
and allow only the first verified success to activate the package.

This extends rather than discards the existing
`processor`/`processor_reference` pattern. The parent fields represent the
winning settlement; attempt rows explain how the cascade got there.
A second successful provider event after settlement must raise an
operations/reconciliation alert rather than disappear as an ordinary
idempotent duplicate.

### 5.3 Mobile-money provider contract

Generalize initialization to carry:

```text
Money
market_country
billing_country
customer {email, phone}
payment_method
payment_network?
callback_url
internal transaction reference
```

Return a typed next action rather than assuming every provider yields only
`checkout_url`:

```text
redirect | deep_link | qr_code | customer_instruction
```

Hosted checkout may cover some markets with only a redirect. Senegal
Orange Money QR/deep-link and Burkina Faso authorization-code behavior
remain market-specific adapters/UX. They should not leak provider names
into the domain model.

## 6. Retention and audit sanity check

[PR #85](https://github.com/block-sig-hash/damdam/pull/85) implemented
six-year transaction retention, independent of account deletion.
[`security.md:96–103`](./security.md#L96) explicitly says the duration is a
reasonable default still requiring legal confirmation.

Currency, amount, market/billing country, payment method/network, winning
processor, provider reference, and verification outcome are legitimate
financial/audit attributes and should share the transaction's retention.
The package copies may disappear earlier with account deletion; the
transaction snapshots must survive.

PR #85's sweep covers `transactions`, but manual HTO payment confirmation
does not currently create one. `manifest_orders` belongs to a manifest via
`ON DELETE CASCADE`, so HTO amount/currency evidence is not demonstrably
protected by the six-year transaction rule. Unifying confirmed HTO payments
under a transaction—or adding an equally explicit six-year order/invoice
retention action—is a prerequisite for claiming consistent financial
retention.

The current `webhook_payload` is retained on the transaction for the full
six years. With mobile money, raw payloads may contain phone number,
provider customer data, IP/device details, and wallet metadata. That is
broader than the canonical financial record and conflicts with data
minimization. Before adding new rails:

1. define an allowlisted verification snapshot;
2. never retain full card numbers, wallet PINs, authorization codes, or
   secrets;
3. decide a shorter operational retention period for raw webhook bodies,
   if they must be stored at all;
4. update `security.md` §10.2/§10.3 and third-party data-flow descriptions;
   and
5. ensure retention audit rows contain transaction/attempt IDs, action, and
   cutoff only—not copied billing country, phone, network, or payload.

PR #85's idempotent deletion mechanism can continue deleting the parent
transaction at six years. New `payment_attempts` should cascade from the
transaction so they cannot outlive it accidentally. If raw payloads use a
shorter table, add a separate scheduled retention action and audit outcome.

## 7. Sequencing and estimate

### 7.1 Foundation required regardless of first market — 5–8 days

| Work | Estimate | Outcome |
|---|---:|---|
| Data model, amendment, migration/backfill | 2–3 days | Generic Money fields, market/billing snapshots, native quote table, manifest/package changes, attempt ledger, NG/NGN backfill |
| Money/pricing/API contracts | 1–2 days | Currency precision utility, server-issued quote selection, decimal-safe API shapes, OpenAPI sync |
| Country routing and provider contracts | 1–2 days | Validated priority/capability resolver, attempt-aware initialization, amount+currency webhook verification |
| Shared display and financial templates | 1–2 days | Mobile/dashboard currency formatter, admin quote editing, PDF/email/WhatsApp structured Money |

Some work overlaps, producing a 5–8 day foundation rather than the sum of
all maximums.

This core should happen even if Ghana—not Senegal—is first. It removes
currency ambiguity from retained financial records, fixes the
destination-versus-market conflation, and prevents a second market from
being another one-off branch.

### 7.2 First Francophone/mobile-money market — 3–7 days

| Work | Estimate | Outcome |
|---|---:|---|
| Market price book and commercial configuration | 0.5–1 day | Approved native quotes, currency, processor priority, settlement account |
| Flutterwave market/network adapter | 1–2 days | Country/network payload, normalized webhook result, sandbox fixtures |
| Mobile-money next-action UX | 1–2 days | Phone/network input and redirect/deep-link/QR/instruction handling as required |
| Payment/idempotency regression and rollout | 0.5–2 days | Cascade, duplicate/late webhook, wrong currency/amount/country, offline return, feature flag and observability |

Total: **8–15 engineering days** for the foundation plus one supported
market. HTO multi-currency invoicing is included. If the first release is
retail-only, HTO UI rollout can be deferred, but the generic manifest-order
schema should still be migrated so the database is not left with two money
models.

## 8. Dependencies and parallel work

- **Flutterwave Mali contradiction:** does not block the foundation.
  Keep `ML` disabled and add its capability/price configuration only after
  written merchant-account confirmation and a working test.
- **Niger and Guinea coverage:** same rule; the model supports them, but no
  quote or route is enabled until a collection rail is proven.
- **Termii account-level testing:** does not block money architecture.
  It gates reliable signup/OTP/notifications in a new country and can run
  in parallel.
- **Processor merchant KYC/settlement:** does not block schema or shared
  services, but it blocks enabling a market. Confirm which legal entity
  contracts with each processor and which currency/account receives
  settlement before seeding live quotes.
- **Price decision:** engineering can build the native quote model in
  parallel, but production seed values require approved retail/wholesale
  amounts, fees, taxes, and margin policy.
- **i18n work:** not a database blocker. Currency formatting and checkout
  instructions should consume the locale architecture proposed in
  [`i18n-scoping.md`](./i18n-scoping.md) rather than create payment-only
  translation logic.

## 9. Recommended implementation gates

1. Approve the three-country-concept vocabulary and native-quote policy.
2. Add a numbered `data-model.md` amendment before migration code and keep
   `api-spec.md`/generated OpenAPI synchronized.
3. Write strict payment/idempotency tests first, including two provider
   attempts, late primary webhook, duplicate webhook, wrong currency,
   excess precision, and market/quote mismatch.
4. Backfill every existing financial row to `market_country=NG`,
   `billing_country=NG`, `currency=NGN`, preserving exact amounts.
5. Migrate clients through an additive compatibility window; do not rename
   all `_ngn` fields in one cross-platform deployment.
6. Minimize webhook retention before mobile-money payloads introduce more
   payer data.
7. Enable only countries with an approved price book, merchant capability,
   settlement path, and end-to-end sandbox/live test.
