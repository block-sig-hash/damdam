# Payment Routing and Termii Coverage Scoping
# DamDam — Version 0.1 · Audit date: 23 July 2026

## 1. Decision summary

Two separate conclusions matter:

1. **Termii does not publish the requested country-by-channel delivery
   matrix.** Its current official documentation says Messaging is global
   across SMS, Voice, WhatsApp, and Email, but neither the public API
   documentation nor the unauthenticated dashboard exposes route
   availability for a named destination. Consequently, none of the eight
   countries can honestly be marked “country/channel confirmed” from
   public first-party evidence alone. This is an evidence gap, not proof
   that Termii lacks coverage.
2. **Country-priority payment routing is small; making it useful in these
   markets is not.** The existing processor abstraction, persisted
   `processor`/`processor_reference`, webhook separation, and
   initialization failover can be retained. A priority resolver is roughly
   1–2 engineering days. Production multi-country collection is closer to
   8–15 engineering days because the current domain is hardcoded to NGN,
   lacks a billing-market signal and mobile-money details, and maps
   Flutterwave “mobile money” to Nigeria-only OPay.

Flutterwave's current collections documentation confirms:

- Ghana: GHS card and Ghana mobile money; the current endpoint reference
  names MTN, Vodafone, and Tigo.
- Burkina Faso: XOF Orange Money and MobiCash.
- Cameroon: XAF MTN and Orange Money.
- Côte d’Ivoire: XOF MTN, Orange Money, Moov, and Wave.
- Senegal: XOF Orange Money and Wave.
- Mali: contradictory first-party documentation—the current method guide
  omits it while the current v3 endpoint reference names it.
- Niger and Guinea: no current first-party mobile-money collections
  confirmation found.

Those findings support Flutterwave-first only for a **verified merchant
account and a supported rail**. They do not support a blanket rule that
all seven Francophone markets are ready.

## 2. Research standard and evidence limits

This audit used current Termii and Flutterwave developer/API documentation
and the Termii-owned dashboard surface. It did not use press releases,
aggregator blogs, or third-party coverage lists.

“Confirmed” below means that a first-party source explicitly names the
country and collection channel. A global marketing/API statement is
reported as such, not silently converted into eight country-level
confirmations. “Not confirmed” does not mean “unsupported”; it means that
the requested fact cannot be established from the available official
surface without an authenticated merchant account or live route test.

Collections and payouts are also kept separate. A provider being able to
send money to a mobile wallet does not prove it can collect a customer
payment from that wallet.

## 3. Termii coverage audit

### 3.1 What Termii officially publishes

Termii's current [Messaging documentation](https://developer.termii.com/messaging)
says its APIs send messages “globally” across SMS, Voice, WhatsApp, and
Email. The [Token documentation](https://developer.termii.com/token)
documents OTP generation, sending, and verification, while Termii's
[current v2 API reference](https://termii.com/docs) exposes per-number
signal scoring and route evaluation across SMS, WhatsApp, voice, and
email.

What is absent is the requested public supported-country list or a
country-by-channel matrix. The v2 route evaluator requires the account API
key and an E.164 phone number; its result is account-, number-, route-, and
time-specific. The unauthenticated dashboard does not expose this matrix
either. The official
[registration country selector](https://staging.app.termii.com/register)
contains all eight target countries, but that only establishes that their
calling codes are accepted during account registration—not that all
delivery channels are enabled.

### 3.2 Country findings

| Target country | SMS OTP | WhatsApp OTP | Voice OTP | First-party conclusion |
|---|---|---|---|---|
| Senegal (`SN`, +221) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Côte d’Ivoire (`CI`, +225) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Mali (`ML`, +223) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Niger (`NE`, +227) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Guinea (`GN`, +224) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Burkina Faso (`BF`, +226) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Cameroon (`CM`, +237) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |
| Ghana (`GH`, +233) | Global claim; not country-verified | Global claim; not country-verified | Global claim; not country-verified | No public route matrix |

This is the strongest defensible answer from Termii's own public
documentation as of the audit date. It would be inaccurate to turn
“global” into eight green ticks without checking account-level routing,
sender-ID requirements, and delivery results.

### 3.3 What DamDam uses today

DamDam uses only Termii's `generic` SMS channel for OTP
([`app/otp/providers/termii.py`](../apps/api/app/otp/providers/termii.py))
and plain family-notification SMS
([`app/notifications/providers.py`](../apps/api/app/notifications/providers.py)).
It does not use Termii WhatsApp OTP or voice OTP. OTP already has a
provider-neutral Termii-primary/Twilio Verify-secondary service and
scheduled delivery failover
([`app/otp/service.py`](../apps/api/app/otp/service.py)); ordinary
notification SMS does not share that two-provider cascade.

DamDam also defaults `termii_base_url` to `https://api.ng.termii.com`.
Termii's current [API introduction](https://developer.termii.com/) says
each account has a dashboard-issued base URL that routes requests to the
appropriate regulatory region. Expansion must verify that the deployed
value is the account's current assigned URL; the `ng` hostname must not
be assumed to be the correct route for every market.

Termii's public v2 docs now describe bring-your-own-vendor and regional
priority routing for Twilio, Africa's Talking, Vonage, MessageBird, or a
custom provider. That could eventually host failover, but adopting Termii
v2 is a separate vendor/control-plane decision and is not necessary for
this expansion.

### 3.4 Required due diligence, roadmap, and fallback

No official country-specific roadmap or ETA was found for any of the
eight countries. Because Termii does not publicly mark any of them
unsupported, there is no evidence-based country gap to assign to a new
provider yet.

Before launch, obtain a written matrix from Termii support or run
authenticated `/v2/routing/evaluate` checks plus live delivery tests for
one controlled number per operator/channel/country. Record sender-ID
registration, WhatsApp template eligibility, voice availability, DLR
quality, latency, and unit price. A route-evaluation success is not a
substitute for a delivered OTP test.

If a country/channel fails that gate:

- retain the existing Twilio Verify secondary for OTP where its own
  merchant account and destination tests pass;
- add a country-aware provider priority to `OTPService` rather than
  replacing Termii globally;
- evaluate Africa's Talking or Infobip only for the failed country/channel,
  behind the existing `OTPProvider` abstraction; and
- separately add an abstraction/fallback for family-notification SMS,
  which currently calls Termii alone.

This is intentionally a contingency design, not a claim that Africa's
Talking or Infobip covers a route that Termii does not.

## 4. Flutterwave country, currency, and mobile-money audit

### 4.1 Confirmed collections

Flutterwave's current
[payment-method table](https://developer.flutterwave.com/v3.0.0/docs/payment-methods)
maps NGN to Nigerian methods, GHS to card/Ghana mobile money, XAF to
card/Francophone mobile money, and XOF to card/Francophone mobile money.
Its more specific
[Francophone mobile-money guide](https://developer.flutterwave.com/v3.0.0/docs/francophone)
is the controlling country/network evidence:

| Target country | Local currency | Current first-party collections evidence | Routing conclusion |
|---|---|---|---|
| Nigeria | NGN | Card, USSD, bank transfer, account, internet banking, NQR, eNaira, OPay | Paystack primary remains sensible; Flutterwave fallback |
| Ghana | GHS | Card + Ghana mobile money; v3 endpoint names MTN, Vodafone, Tigo | Paystack primary per requested policy; Flutterwave fallback, with Flutterwave viable for MoMo |
| Burkina Faso | XOF | Orange Money, MobiCash | Flutterwave-primary candidate after merchant enablement test |
| Cameroon | XAF | MTN, Orange Money | Flutterwave-primary candidate after merchant enablement test |
| Côte d’Ivoire | XOF | MTN, Orange Money, Moov, Wave | Flutterwave-primary candidate after merchant enablement test |
| Senegal | XOF | Orange Money, Wave | Flutterwave-primary candidate after merchant enablement and flow test |
| Mali | XOF | Current guide omits Mali; current v3 endpoint reference says Cameroon, Côte d’Ivoire, Mali, Senegal | **Do not mark launch-ready:** obtain written/account-level confirmation |
| Niger | XOF | No current first-party collections confirmation found | **Not confirmed; do not route by assumption** |
| Guinea | GNF | No current first-party collections confirmation found | **Not confirmed; do not route by assumption** |

The Ghana network list is in Flutterwave's current
[Ghana charge reference](https://developer.flutterwave.com/v3.0/reference/charge-via-ghana-mobile-money).
The Mali discrepancy is between the current country/network guide, which
lists only BF/CM/CI/SN, and the current
[v3 Francophone charge reference](https://developer.flutterwave.com/v3.0/reference/charge-via-francophone-mobile-money),
which names Mali but gives incomplete example country values. Merchant
enablement and a live/sandbox test must settle it.

The generic payment-method page also appears to transpose the XAF/XOF
option identifiers in its region table, while the prose immediately above
uses `mobilemoneyxaf` for Central Africa and `mobilemoneyxof` for West
Africa. Implementation should follow a tested country/network mapping,
not copy that table mechanically.

### 4.2 Flows that are not a string/config swap

Francophone direct charge requires phone number, ISO country, network,
amount, currency, email, and transaction reference. The current DamDam
initialization carries only email plus an NGN amount and generic channel
list.

Senegal Orange Money is a specific product flow: Flutterwave says the old
push flow stopped being supported on 5 December 2025. Web checkout must
render a QR; mobile must follow the returned redirect/deep-link
authorization flow. Burkina Faso Orange Money additionally needs a
customer-generated authorization code. Ghana mobile money also returns an
authorization redirect. These paths require mobile/WebView UX, return
handling, and tests—not only a different `payment_options` string.

Flutterwave account KYC, country onboarding, local settlement currency,
fees, reserves, and method enablement remain commercial prerequisites.
API documentation establishes technical surface area, not approval for
DamDam's specific merchant account.

## 5. Current payment architecture

### 5.1 What is already reusable

- `PaymentProvider` cleanly abstracts initialization and webhook parsing
  for Paystack and Flutterwave
  ([`providers.py`](../apps/api/app/payments/providers.py)).
- `PaymentService._initialize_with_failover` iterates configured primary
  then secondary and falls through only when initialization raises a
  provider error
  ([`service.py`](../apps/api/app/payments/service.py)).
- `transactions.processor` records the selected provider and
  `processor_reference` has a partial unique index. Each webhook route
  dispatches to the correct provider parser, then the service performs
  reference, amount, and idempotent-status checks
  ([`models.py`](../apps/api/app/packages/models.py)).
- Both processors return the same API-facing `checkout_url`, so the
  frontend does not need a provider-selection screen.

The `processor`/`processor_reference` pattern should remain. It already
solves the vendor-identity and webhook-idempotency part of this change.

The current cascade only covers **checkout initialization failure**. It
does not automatically switch processors after a user abandons or fails a
checkout. Preserving existing semantics means country routing chooses the
first initialization attempt, then uses the other configured processor
only if initialization itself fails.

### 5.2 Why production country routing is deeper than configuration

The code and schema are Nigeria-specific in six ways:

1. `PricingTier.ngn_price`, `Transaction.amount_ngn`,
   `PaymentInitialization.amount_ngn`, and `PaymentWebhookEvent.amount_ngn`
   encode NGN in the domain.
2. Both providers send `currency: "NGN"` and both webhook parsers reject
   every non-NGN event.
3. Flutterwave maps generic `mobile_money` to `opay`, a Nigerian option.
4. Mobile-money provider results are collapsed into
   `PaymentMethod.BANK_TRANSFER`; the enum has no mobile-money value.
5. Provider initialization lacks customer phone, billing country,
   selected network, and a typed authorization/next-action result.
6. Receipts, API shapes, and frontend price display are Naira-specific.

`users.destination_country` and `packages.destination_country` cannot
safely select a payment processor. They identify the trip destination and
currently default to Saudi Arabia; they do not identify where the buyer
or payment instrument is based. Payment routing needs a separately named,
validated **sale market/billing country** captured at checkout or stored
on the user/organization.

## 6. Proposed per-country routing

### 6.1 Configuration and resolver

Retain provider abstractions and add an ordered policy keyed by sale
market, for example:

```text
NG -> [paystack, flutterwave]
GH -> [paystack, flutterwave]
BF, CM, CI, SN -> [flutterwave, paystack]
ML -> disabled until account-level confirmation
NE, GN -> disabled until a supported collection path is confirmed
default -> explicit unsupported-market error
```

Do not silently fall back to the current global pair for an unknown
country. Configuration should be validated at startup for known provider
names, no duplicates, at least one configured provider, and a deliberate
unsupported-market state.

The requested “Flutterwave primary for all Francophone markets” should
therefore be expressed as policy intent, but ML/NE/GN must remain launch
gates rather than pretend-supported routes.

### 6.2 Required domain and API work

For real local-currency/mobile-money collection:

1. Add an explicit checkout `market_country`; validate it against the
   authenticated user's eligible market rather than trusting arbitrary
   client input.
2. Generalize price and transaction money fields to decimal `amount` +
   ISO `currency`. Preserve immutable price/currency snapshots on the
   transaction.
3. Add per-market prices (NGN, GHS, XOF, XAF, and only GNF if a collection
   route is actually approved). This is distinct from package
   destination pricing.
4. Extend provider initialization with customer phone, country, optional
   mobile network, currency, and a typed authorization result. Use
   market-specific Flutterwave option identifiers/direct-charge payloads.
5. Verify webhook processor, reference, status, exact currency and amount
   before activation; never convert currencies during webhook matching.
6. Represent mobile money as its own payment method and retain the network
   in metadata/auditing.
7. Support redirect, deep-link, and where necessary QR or authorization
   code next actions in the mobile checkout.
8. Update receipt/notification money formatting and all API/mobile
   schemas that currently say `amount_ngn`.

This requires a numbered `data-model.md` amendment, synchronized
`api-spec.md`, PRD/frontend documentation updates, migration/backfill
policy, and the strict payment/idempotency tests required by
`testing-qa.md`.

## 7. Sizing and decision gates

| Scope | Estimate | What it includes |
|---|---:|---|
| Termii evidence closure | 1–3 elapsed business days, low engineering effort | Vendor response, authenticated route checks, controlled operator/channel delivery tests |
| Country-priority resolver only | 1–2 engineering days | Config model, resolver, startup validation, unit tests; still NGN/hosted-checkout only and therefore not market-ready |
| Multi-currency transaction/pricing foundation | 3–5 engineering days | Model amendment/migration, schemas, amount+currency verification, receipts, API and tests |
| Flutterwave country/mobile-money paths | 3–6 engineering days | Ghana/BF/CM/CI/SN payloads, phone/network fields, redirect/deep-link/QR handling, webhook fixtures |
| QA, docs, regression, rollout controls | 2–4 engineering days | Idempotency/failover tests, sandbox/live smoke tests, feature flags, observability and spec sync |
| **Production-ready supported-market routing** | **8–15 engineering days** | Roughly 2–3 engineering weeks; merchant approval/vendor response time is additional |

ML/NE/GN are not included as launch-ready mobile-money markets in that
estimate. Each requires confirmed Flutterwave enablement or a separately
scoped collection provider. Likewise, Termii channel certification is
external elapsed time and should gate launch even though it is not much
coding.

## 8. Recommended go/no-go checklist

1. Get Termii's written country/channel/sender-ID matrix and run delivered
   OTP tests for the intended operators.
2. Get Flutterwave to confirm merchant-account collections, settlement,
   and network enablement for each proposed sale market; resolve Mali's
   documentation conflict explicitly.
3. Decide where authoritative sale market comes from; do not reuse trip
   `destination_country`.
4. Approve a local-currency price book before engineering starts.
5. Greenlight BF/CM/CI/SN only after their mobile-money UX is accepted;
   gate ML/NE/GN independently.
6. Treat the 1–2 day resolver as a useful slice, not as the complete
   expansion implementation.
