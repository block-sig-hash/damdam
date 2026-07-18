# API Specification
# DamDam — Version 0.1

This document is the canonical route inventory and contract.
FastAPI generates the live, always-current OpenAPI 3.0 spec at
`/docs` and `/openapi.json` directly from the Pydantic models
defined against data-model.md — that generated spec should be
exported and committed to `docs/api-spec.yaml` on every schema
change (CI step, see infrastructure.md §11.4), with this markdown
file kept as the human-readable companion.

**Base URL:** `https://api.damdam.app/v1`
**Auth:** Bearer JWT (pilgrim + admin), separate JWT scope for HTO
operators (`aud: hto_dashboard` claim), separate scope for admin
(`aud: admin`)
**Content-Type:** `application/json` throughout, except file
uploads (`multipart/form-data`) and webhooks (raw payload per
provider spec)

---

## 7.1 Authentication

```
POST   /auth/otp/request
  Body: { phone_number: string }
  200: { message: "OTP sent" }
  429: { error: "rate_limited", retry_after: int }
  409: { error: "account_exists" }
  503: { error: "otp_unavailable" }

POST   /auth/otp/verify
  Body: { phone_number: string, otp: string, platform: "ios"|"android" }
  200: { access_token, refresh_token, user: {..}, is_new_user: bool }
  400: { error: "invalid_otp" | "otp_expired" }
  423: { error: "locked", retry_after: int }
  503: { error: "otp_unavailable" }

POST   /auth/pin/set
  Auth required
  Body: { pin: string }
  200: { message: "PIN set" }
  400: { error: "pin_too_weak" }

POST   /auth/pin/verify
  Auth required (session token, pre-PIN-unlock state)
  Body: { pin: string }
  200: { unlocked: true }
  400: { error: "invalid_pin" | "pin_not_set" }
  423: { error: "locked", retry_after: int }

POST   /auth/pin/recovery/request
  Body: { phone_number: string }
  200: { message: "OTP sent" }
  404: { error: "account_not_found" }
  429: { error: "rate_limited", retry_after: int }
  503: { error: "otp_unavailable" }

POST   /auth/pin/recovery/verify
  Body: { phone_number: string, otp: string, platform: "ios"|"android" }
  200: { access_token, refresh_token, user: {..}, is_new_user: false }
  Resets the PIN attempt lock and returns an authenticated session;
  the client then replaces the PIN through `/auth/pin/set`.
  400: { error: "invalid_otp" | "otp_expired" }
  423: { error: "locked", retry_after: int }

POST   /auth/token/refresh
  Body: { refresh_token: string }
  200: { access_token, refresh_token }
  401: { error: "invalid_refresh_token" }

POST   /auth/hto/register
  Body: { business_name, operator_name, email, password,
          phone_number, nahcon_licence_number }
  201: { message: "Verification email sent" }
  409: { error: "email_already_registered" }

POST   /auth/hto/verify-email
  Body: { token: string }
  200: { message: "Email verified, pending admin approval" }
  400: { error: "invalid_verification_token" }

POST   /auth/hto/login
  Body: { email, password }
  200: { access_token, refresh_token, operator: {..} }
  401: { error: "invalid_credentials" }
  403: { error: "email_not_verified" | "pending_approval" | "rejected" }
```

---

## 7.2 Pilgrim Profile & Onboarding

```
GET    /me
  Auth required
  200: { id, phone_number, first_name, last_name, email,
          verified_cli, departure_date, platform, packages: [..] }

PATCH  /me
  Auth required
  Body: { first_name?, last_name?, email?, departure_date? }
  200: { ...updated user }

PUT    /me/device-token
  Auth required
  Body: { fcm_token: string, platform: "ios" | "android" }
  200: { registered: true }
  Upserts by globally unique FCM app-installation token and refreshes
  its user association/timestamp. Added by US-13 to fill the push-token
  schema gap documented in data-model.md §6.20.

POST   /me/family-contact
  Auth required
  Body: { phone_number: string, name?: string }
  201: { id, phone_number, name, notified_of_nomination: bool }
  409: { error: "family_contact_exists" }
  503: { error: "notification_unavailable" }

PATCH  /me/family-contact
  Auth required
  Body: { phone_number?: string, name?: string }
  200: { ...updated contact }
  404: { error: "family_contact_not_found" }
  503: { error: "notification_unavailable" }

GET    /me/emergency-contact
  Auth required
  US-12 AC-12.2 — the HTO operator's number is per-pilgrim, read
  live from the pilgrim's assigned organization, not static
  content (see data-model.md §6.20). DamDam's own support WhatsApp
  number and the Arabic phrasebook are bundled client-side per
  AC-12.3 and are not part of this response.
  200: { hto_operator_name, hto_operator_phone_number }
       Both null for a direct/retail pilgrim with no assigned HTO.

GET    /activation/{activation_code}
  No auth required (pre-login preview, shown before OTP/PIN)
  200: { valid: bool, reason: "activation_code_already_used"|
          "activation_code_expired"|null, organization_name,
          pricing_tier_name }
  404: { error: "activation_code_invalid" }

POST   /me/activation/redeem
  Auth required — works identically for a pilgrim who just
  completed OTP/PIN (AC-07.4) or one already signed in (AC-07.5)
  Body: { activation_code: string }
  200: { package_id, pricing_tier_name, data_gb_total,
          pstn_minutes_total, status: "active" }
  403: { error: "activation_code_phone_mismatch" }
  404: { error: "activation_code_invalid" }
  409: { error: "activation_code_already_used" }
  410: { error: "activation_code_expired" }

POST   /me/verify-cli
  Auth required
  200: { message: "Verification OTP sent to registered number" }

POST   /me/verify-cli/confirm
  Auth required
  Body: { otp: string }
  200: { verified_cli: true }

POST   /me/device-compatibility
  Auth required
  Body: { platform: "ios"|"android", device_model: string,
          os_version?: string, esim_supported: bool }
  201: { logged: true }
```

---

## 7.3 Pricing & Packages

```
GET    /pricing/tiers
  No auth required (public pricing page)
  200: { tiers: [{ id, name, ngn_price, data_gb, pstn_minutes,
          is_group_tier, min_group_size?, max_group_size?,
          per_person_ngn_rate? }] }
  `ngn_price` is the current admin-set `pricing_tiers.ngn_price`
  value. The read path performs no FX lookup or client-specific
  price calculation (prd.md §5.9, data-model.md §6.16).

POST   /packages/purchase
  Auth required
  Body: { pricing_tier_id: string, group_size?: int }
  200: { package_id, processor: "paystack"|"flutterwave",
          processor_reference, checkout_url }
  400: { error: "invalid_group_size" }
  404: { error: "pricing_tier_not_found" }
  503: { error: "payment_unavailable" }
  Note: `processor` and `checkout_url` are generic — Paystack is
  used unless its checkout initialization call fails, in which
  case the backend falls back to Flutterwave automatically before
  this response is returned. See `data-model.md` §6.7. The client
  never needs processor-specific logic; it opens `checkout_url` in
  a web view regardless of which processor issued it.

GET    /packages/{id}/status
  Auth required
  200: { status: "pending"|"active"|"expired",
          data_gb_total, data_gb_remaining,
          pstn_minutes_total, pstn_minutes_remaining }
  Used by the checkout success-screen polling fallback (§5.3
  failure mode in prd.md) and Home balance refresh (US-17). The
  `*_total` fields are the immutable purchase-time package snapshots,
  not values re-read from a mutable pricing tier.
  Ownership is enforced against the authenticated pilgrim; another
  user's package returns 404.

GET    /packages/{id}/geofence
  Auth required
  200: { latitude: number, longitude: number, radius_meters: number,
          request_id: string }
  404: { error: "package_not_found" }
       | { error: "destination_geofence_not_configured" }
  Resolves arrival-alert configuration from the package's immutable
  destination_country snapshot. Ownership is enforced exactly as for
  /packages/{id}/status; another user's package returns 404. A destination
  without a configured row fails closed and never falls back to SA.

GET    /me/packages
  Auth required
  200: { packages: [{ id, tier_name, status, group_size,
          data_gb_remaining, pstn_minutes_remaining, expires_at }] }
```

---

## 7.4 eSIM

```
POST   /packages/{id}/esim/issue
  Auth required
  Triggered automatically post-payment; also callable manually as
  a retry if issuance failed
  200: { esim_profile_id, iccid, activation_code_lpa,
          qr_code_url, status }
  502: { error: "aggregator_unavailable" }
  Idempotent by package: an already-issued profile is returned without
  calling an aggregator again. Supplier order comes from
  ESIM_VENDOR_PRIMARY/SECONDARY/TERTIARY. If all three fail, the same
  response records a persistent backoff job; attempt 3 enters the admin queue.
  eSIM Access uses its signed order/query API and the configured Saudi plan-code
  map; an accepted but still-allocating order is retried against eSIM Access
  with the same package transaction id and does not cascade (which would buy a
  duplicate). Monty Mobile and 1GLOBAL issuance URLs target their configured
  partner adapters because their commercial wire schemas are partner-gated.

GET    /packages/{id}/esim
  Auth required
  200: { esim_profile_id, iccid, qr_code_url, status,
          downloaded_at?, activated_at? }

POST   /packages/{id}/esim/mark-downloaded
  Auth required
  Called by the app after invoking the platform eSIM download API
  (Android) or after the user confirms manual installation (iOS —
  no platform callback exists, so this is a self-reported user
  confirmation on iOS specifically)
  200: { status: "downloaded" }

POST   /packages/{id}/esim/mark-activated
  Auth required
  Called after the app's connectivity check succeeds
  post-activation
  200: { status: "activated" }
  Idempotent: an already-activated profile keeps its original
  activated_at timestamp.
```

`mark-activated` is implemented by US-13. The existing `GET /hto/pilgrims` response derives its
`esim_status` from the package's `esim_profiles.status` (`issued`, `downloaded`,
or later `activated`), while the pre-existing `incompatible` follow-up state
takes precedence.

---

## 7.5 Voice / Calling

**Vendor decided: Telnyx.** The original draft of this section was
written against Twilio's specific API shapes as a placeholder,
explicitly flagged as provisional pending the Phase 0 quote
comparison (`prd.md` §6) between Twilio and Telnyx. That comparison
resolved in Telnyx's favor. As flagged in the original draft, this
is a real amendment, not a find-and-replace — Telnyx's Call Control
API is webhook-and-REST-command driven (the app issues explicit
commands like dial/answer/hangup via API calls in response to
webhook events), structurally different from Twilio's TwiML
pattern (where the webhook handler returns XML markup Twilio then
executes). The endpoints below reflect that shape at the contract
level; confirm exact Telnyx payload field names against Telnyx's
current API docs at implementation time, the same way Codex
confirmed exact field shapes against Termii's and Twilio's official
docs when implementing US-01.

```
GET    /voice/eligibility?phone_number={nigerian_number}
  Auth required
  Contextual lookup used after a complete number is entered/selected; it does
  not enumerate users and accepts only a full Nigerian number.
  200: { allowed, call_type: "pstn" | "app_to_app",
         destination?: string, reason?: "cli_not_verified" |
         "pstn_balance_exhausted", pstn_minutes_remaining }
  Registered target → app_to_app, allowed even when the caller is unverified
  or has zero PSTN minutes. The target's Telnyx SIP username is provisioned and
  returned only by POST /voice/token, keeping this GET lookup side-effect free.
  Non-registered target → PSTN, requiring verified_cli and positive balance.

POST   /voice/token
  Auth required
  Body: { to_number: string }
  200: { token: string, sip_username: string, expires_at,
         call_type: "pstn" | "app_to_app", destination: string }
  Short-lived Telnyx WebRTC credential for the client SDK
  (cross-platform — same endpoint serves iOS and Android)
  Each user has a distinct Telnyx telephony credential. The app requests a
  token only when starting a call and refreshes before `expires_at`.
  403 cli_not_verified: PSTN only; app-to-app remains allowed
  409 pstn_balance_exhausted: PSTN only; app-to-app remains allowed

POST   /webhooks/telnyx/call-events
  Telnyx-signed webhook (Call Control API), not user-facing
  Headers: telnyx-timestamp, telnyx-signature-ed25519
  Body: Telnyx Call Control event payload (call initiated,
  answered, hangup, etc.)
  Signature: base64 Ed25519 over `{timestamp}|{raw_request_body}` using the
  account public key, with a 5-minute replay window. This follows the existing
  reject-before-parse signed-webhook pattern but not Paystack's HMAC algorithm.
  401 invalid_webhook_signature: missing, malformed, stale, or invalid signature
  400 invalid_webhook_payload: authentic signature but malformed event envelope
  200: on the client call.initiated event, looks up the SIP credential owner,
  requires verified_cli + a positive balance for PSTN, and creates the outbound
  leg with `from` set to that user's verified Nigerian number and
  `time_limit_secs` capped to the current balance; bridges on call.answered.
  On call.hangup, writes one call_log keyed by Telnyx `call_leg_id` and deducts
  duration from the locked active package row. Duplicate events are no-ops and
  the balance is clamped at zero.

GET    /me/calls
  Auth required
  Query: ?limit=20
  200: { calls: [{ id, call_type, to_number?, duration_seconds,
          pstn_minutes_charged, started_at }] }
```

---

## 7.6 Check-in & SOS

```
POST   /checkins
  Auth required
  Body: { client_generated_id: uuid, timestamp: iso8601,
          latitude?: float, longitude?: float }
  200: { id, received_at }
  Idempotent on client_generated_id — safe to retry
  409: checkin_id_conflict (UUID already belongs to another pilgrim)
  429: checkin_rate_limited (a different check-in was accepted in the last 15 min)

POST   /sos
  Auth required
  Body: { client_generated_id: uuid, timestamp: iso8601,
          latitude?: float, longitude?: float }
  200: { id, status: "active" }
  Idempotent on client_generated_id

POST   /sos/{id}/cancel
  Auth required
  200: { status: "cancelled" }

GET    /me/checkins
  Auth required
  Query: ?limit=10
  200: { checkins: [{ id, timestamp, latitude?, longitude? }] }

GET    /webhooks/meta/whatsapp
  Meta subscription verification; validates hub.verify_token and echoes
  hub.challenge as text for hub.mode=subscribe

POST   /webhooks/meta/whatsapp
  Meta WhatsApp delivery-status webhook — shared by check-in (AC-15.10) and
  SOS family (AC-22.3); a wamid uniquely correlates to at most one of the
  two notification tables, so one signed endpoint checks both.
  Verifies X-Hub-Signature-256 (HMAC SHA256 of the raw body using the Meta app
  secret) before parsing. A delivered `wamid` suppresses the scheduled SMS
  fallback. Missing/malformed signatures return 401 invalid_webhook_signature;
  authentic malformed JSON returns 400 invalid_webhook_payload.
  200: { processed: int }
```

---

## 7.7 HTO Dashboard — Manifests

```
POST   /hto/manifests
  HTO auth required
  Body: { name?: string }
  201: { manifest_id, status: "draft" }

POST   /hto/manifests/{id}/upload
  HTO auth required
  Body: multipart CSV file (`file`), UTF-8, maximum 500 data rows
  Required headers: first_name, last_name, phone_number
  Optional headers: passport_number, seat_number
  200: { total_rows, valid_rows, invalid_rows: [{ row_number,
          reason }], preview: [{ id, row_number, first_name,
          last_name, phone_number, passport_number?, seat_number?,
          validation_status: "valid"|"duplicate_warning", warning? }] }
  Duplicate phone numbers remain in preview with duplicate_warning;
  malformed rows remain staged only until confirmation.
  400: malformed_csv | missing_required_columns | row_limit_exceeded
  415: csv_required

POST   /hto/manifests/{id}/confirm
  HTO auth required
  Removes invalid staged rows and retains valid/duplicate-warning rows.
  200: { status: "validated", pilgrim_count: int }
  400: no_valid_rows
  409: manifest_already_confirmed

POST   /hto/manifests/{id}/group
  HTO auth required
  Body: { manifest_pilgrim_ids: [uuid], group_size: int }
  Groups selected (unordered) rows under a shared family_group_id
  for a Family-tier purchase (data-model.md §6.4)
  200: { family_group_id: uuid }

PUT    /hto/manifests/{id}/group/{group_id}
  HTO auth required
  Body and response: same as POST; replaces the complete unordered group

DELETE /hto/manifests/{id}/group/{group_id}
  HTO auth required
  204: removes the grouping while leaving pilgrims unordered

GET    /hto/pricing-tiers
  HTO auth required
  200: { tiers: [{ id, name, retail_price_ngn, wholesale_price_ngn,
          estimated_margin_ngn, is_group_tier, min_group_size?,
          max_group_size? }] }

POST   /hto/manifests/{id}/order
  HTO auth required
  Body: { pricing_tier_id: string, manifest_pilgrim_ids: [uuid] }
  Explicit pilgrim selection required — a manifest can have
  multiple orders across different tiers/groupings
  (data-model.md §6.5). manifest_pilgrim_ids must all currently
  have manifest_order_id = NULL.
  200: { manifest_order_id, total_ngn, invoice_url }
  400: invalid_pilgrim_selection | family_group_required |
       complete_family_group_required | individual_pilgrims_required
  409: { error: "pilgrims_already_ordered",
         details: { pilgrim_ids: [uuid] } }

GET    /hto/manifests/{id}/order/{order_id}
  HTO auth required
  200: { id, tier_name, pilgrim_count, wholesale_price_ngn,
         total_ngn, status, invoice_url, payment_confirmed_at? }

GET    /hto/manifests/{id}/order/{order_id}/invoice
  HTO auth required; ownership is checked against both manifest and order
  200: application/pdf

GET    /hto/manifests/{id}/orders
  HTO auth required
  200: { orders: [{ id, tier_name, pilgrim_count, total_ngn,
          status }] }

GET    /hto/manifests/{id}/unordered-pilgrims
  HTO auth required
  200: { pilgrims: [{ id, name, phone_number, family_group_id? }] }
  Powers the selection pool for both the Group and Order screens

GET    /hto/manifests
  HTO auth required
  200: { manifests: [{ id, name, status, valid_rows,
          created_at }] }
```

---

## 7.8 HTO Dashboard — Pilgrim Monitoring

```
GET    /hto/pilgrims
  HTO auth required
  Query: ?manifest_id= (filters to one manifest; risk-sort AC-18.1,
         amber-highlight AC-18.3, and search AC-18.7 are all
         implemented client-side against this same full-list
         response, not as new server query params — a per-manifest
         roster is small enough that server-side pagination/sort
         isn't warranted yet)
  200: { pilgrims: [{ id, name, phone_number, tier, esim_status,
          last_checkin_at?, sos_status, activation_status }] }

GET    /hto/pilgrims/{id}
  HTO auth required
  200: { ...full detail including checkin history }

GET    /hto/sos-alerts
  HTO auth required
  Query: ?status=active
  200: { alerts: [{ id, pilgrim_name, pilgrim_phone, timestamp,
          latitude?, longitude?, status }] }

POST   /hto/sos-alerts/{id}/resolve
  HTO auth required
  200: { status: "resolved" }
  409: sos_already_cancelled (a pilgrim already cancelled this alert)
  A resolved alert's still-pending/failed trigger-event notification rows
  are never sent or retried again (data-model.md §6.26).

POST   /hto/push-subscriptions
  HTO auth required
  Body: { fcm_token: string }
  204
  Associates the operator's browser FCM registration token with that
  organization's own SOS push topic (hto-{organization_id}) via Firebase's
  Instance ID API, server-side — a browser cannot subscribe itself
  directly, it can only obtain the token from Firebase's client SDK.
  503: push_subscription_failed (Firebase unavailable or misconfigured)

GET    /hto/reports/provisioning.csv
  HTO auth required
  Query: ?manifest_id= (optional; omitted = all of the operator's
         manifests) &date_from=&date_to= (optional, YYYY-MM-DD,
         filtered on purchase_date)
  200: text/csv, Content-Disposition: attachment
       Columns: name, phone, tier, purchase_date, esim_status,
       check_in_count, sos_events (AC-20.2, in this order)
       Generated synchronously (AC-20.4: measured under 30s at 500
       rows in real testing — see api-spec.md §7.21, no async/job_id
       path needed). Only rows whose manifest_order has reached
       `provisioned` are included (data-model.md §6.14).
  See §7.21 for the full amendment, including a pre-existing spec
  discrepancy this replaces.
```

---

## 7.9 Webhooks (Inbound, external providers)

```
POST   /webhooks/paystack
  Paystack-signed (HMAC SHA512 header verification)
  Handles: charge.success
  Idempotent on transaction.processor_reference (prd.md §5.3;
  data-model.md §6.7 — field renamed from paystack_reference)
  200: { processed: true|false } (`false` for duplicates and
       non-success events, so processor retries stop cleanly)
  401: { error: "invalid_webhook_signature" }

POST   /webhooks/flutterwave
  Flutterwave-signed (verif-hash header verification)
  Handles: charge.completed
  Same idempotency pattern as the Paystack webhook above, on
  transaction.processor_reference. Normally this follows a
  Flutterwave fallback checkout; if the primary timed out after
  accepting the same generated reference, the first valid signed
  success webhook from either processor wins and records the actual
  processor without provisioning twice.
  Same response/error contract as Paystack. Both routes activate
  the pending package synchronously before returning, then dispatch
  the receipt with a durable retry checkpoint (data-model.md §6.18).

POST   /webhooks/telnyx/call-events  (see §7.5)

POST   /webhooks/whatsapp/status
  Meta-signed
  Delivery status callbacks for outbound WhatsApp messages —
  feeds sos_notifications.status (data-model.md §6.2)

POST   /webhooks/otp/termii
  Termii-signed delivery report (`X-Termii-Signature`, HMAC-SHA512)
  Marks the correlated OTP delivery as confirmed. Returns 200 for
  valid reports, including non-delivered terminal states; invalid
  signatures return 401. This is an internal provider callback and
  does not expose a vendor-specific shape to app clients.
```

---

## 7.10 Admin

```
GET    /admin/hto-operators
  Admin auth required
  Query: ?status=pending|approved|rejected
  200: { operators: [{ id, business_name, operator_name, email,
          phone_number, nahcon_licence_number, email_verified,
          approval_status, created_at }] }

POST   /admin/hto-operators/{id}/approve
  Admin auth required
  200: { approval_status: "approved" }
  Triggers operator approval notifications via email + WhatsApp

POST   /admin/hto-operators/{id}/reject
  Admin auth required
  Body: { reason: string }  (reject only)
  200: { approval_status: "rejected" }

GET    /admin/manifest-orders
  Admin auth required
  Query: ?status=awaiting_payment&search=
  200: { orders: [{ id, hto_business_name, manifest_name,
          pilgrim_count, total_ngn, invoice_url, days_pending }] }

GET    /admin/manifest-orders/{id}/invoice
  Admin auth required
  200: application/pdf

POST   /admin/manifest-orders/{id}/confirm-payment
  Admin auth required
  200: { status: "provisioning" }
  Idempotently records manual payment and triggers the background
  provisioning job (data-model.md §6.14)

GET    /admin/pricing-tiers
  Admin auth required
  200: { tiers: [{ id, name, ngn_price, is_group_tier }] }

PATCH  /admin/pricing-tiers/{id}
  Admin auth required
  Body: { ngn_price: number }  (> 0)
  200: { id, name, old_ngn_price, new_ngn_price, percent_change,
          changed_at }
  Writes a `pricing_tier_price_changes` audit row (admin, old
  value, new value, timestamp — AC-26.4); the new price is live
  immediately for subsequent reads (prd.md §5.9/US-26)

GET    /admin/sos-notifications/failed
  200: { notifications: [{ id, pilgrim_name, channel,
          failure_reason, sos_timestamp, retry_count }] }

POST   /admin/sos-notifications/{id}/retry
POST   /admin/sos-notifications/retry-bulk
  Body: { notification_ids: [uuid] }

GET    /admin/device-compatibility-log
  Query: ?esim_supported=false&platform=ios
  Used to build the "known incompatible devices" list

POST   /admin/packages/{id}/cancel
  Admin auth required
  200: { id, status: "cancelled" }
  404: package_not_found
  AC-25.3/25.4 (see data-model.md §6.30/§6.31): sets the package's
  status to `cancelled` and writes an `audit_log` row
  (`package_cancelled_by_admin`). Cancel-only — no balance
  reversal, chain re-linking, or payment refund/credit; calling it
  on an already-cancelled package is a no-op (idempotent, no
  duplicate audit row). Lets an admin undo one side of a mistaken
  duplicate purchase; see §7.13 for why this is a narrow exception
  rather than a reopening of "manual package editing."
```

---

## 7.11 Rate Limiting

| Endpoint group | Limit |
|---|---|
| `/auth/otp/request` | 3 per phone number per hour |
| `/auth/pin/verify` | 5 attempts, then 30-min lock |
| `/checkins` | 1 per 15 min per user |
| `/sos` | No limit |
| All other authenticated endpoints | 100 req/min per user |
| Public endpoints (`/pricing/tiers`) | 60 req/min per IP |

## 7.12 Error Response Shape

Standard across all endpoints:

```json
{
  "error": "machine_readable_code",
  "message": "Human-readable explanation",
  "details": {}
}
```

---

## 7.13 Admin UI Scope

The admin endpoints above are surfaced through 5 bare-bones
screens in the shared HTO/Admin Next.js dashboard (not a raw API
tool) — see frontend-dashboard.md §9.1, Screens 13–18:

1. **HTO Operator Approvals** — `/admin/hto-operators/*`
2. **Manifest Payment Confirmation** — `/admin/manifest-orders/*`
   (highest-traffic admin screen pre-Hajj-season; needs
   search/filter by HTO name from day one)
3. **Failed Notification Queue** — `/admin/sos-notifications/*`
   (includes bulk retry, given a systemic outage could produce
   many failed rows at once)
4. **Device Compatibility Log** — `/admin/device-compatibility-log`
   (read-only, now filterable by platform)
5. **Naira Pricing Management** — `/admin/pricing-tiers/*`
   (manual, on-demand price updates per prd.md §5.9/US-26 — no
   live FX API dependency, no scheduled job)

Auth: `admin_users` table with role-based route guards in Next.js
middleware, same JWT-scope pattern (`aud: admin`) as the HTO
dashboard's `aud: hto_dashboard` distinction — both dashboards
share one Next.js codebase with role-conditional routing.

Explicitly not in the admin UI for MVP: user search/lookup, manual
package editing, refund processing, analytics dashboards. Anything
outside these four screens is a direct database action for MVP,
acceptable given expected pilot volume.

`POST /admin/packages/{id}/cancel` (§7.10, added for US-25 AC-25.3)
is a narrow, deliberate exception to "no manual package editing":
it can only flip a package to `cancelled`, nothing else about a
package is editable through it. It exists because chaining
(data-model.md §6.30) means a mistaken duplicate purchase is no
longer silently blocked — an admin needs a way to undo one side of
it. It does not reverse balance, re-link a chain, or touch
payment/refund state, so it doesn't reopen the refund-processing
exclusion above; automatic reversal remains future work tied to
the payment-abstraction refund capability in
scaling-infrastructure.md.

---

## 7.14 Amendment — US-01 OTP Delivery Failover Contract

US-01's provider failover requires a delivery-confirmation input,
not merely confirmation that Termii accepted the send request. The
Termii delivery-report webhook above is therefore part of the OTP
provider abstraction: its `message_id` is correlated to short-lived
Redis challenge state and never stored on the pilgrim account.

`POST /auth/otp/request` now documents the already-required
`account_exists` result (AC-01.7) and the total-provider-outage result
from PRD §5.1. Neither response leaks which provider was attempted.

---

## 7.15 Amendment — US-02 PIN Recovery Contract

AC-02.4 requires OTP recovery to remain available even while PIN
verification is locked. The dedicated recovery request route therefore
reuses the provider-agnostic OTP service while explicitly allowing an
existing account; ordinary signup requests continue returning
`account_exists` per AC-01.7. Successful recovery clears only the PIN
failure counters, issues a normal authenticated session, and requires
the pilgrim to choose a replacement PIN through the existing PIN-set
route.

---

## 7.16 Amendment — US-04 HTO Registration and Approval Contract

US-04 makes email verification and manual DamDam-admin approval
independent activation gates. An operator therefore receives an
`email_not_verified` response until the signed 24-hour verification
link is used, then `pending_approval` until an admin reviews the stored
NAHCON licence number. The licence is displayed to the admin exactly
as submitted and is not sent to a programmatic validation provider
for MVP.

The HTO approvals list is added so the specified Admin Screen 14 can
review pending registrations without direct database access. Approval
is admin-authenticated and dispatches both Resend email and WhatsApp
Business notifications through internal provider abstractions; vendor
response shapes do not leak into the API contract.

---

## 7.17 Amendment — Organization-Backed HTO Identity

The HTO authentication and admin-review endpoints are now backed by the
generic `organizations` entity described in `data-model.md` §6.11. US-04
registrations always create an organization with `org_type = hto_operator`;
enterprise and government values are reserved and are not accepted by the HTO
login or approval flow.

This is deliberately not a public contract change. The existing `/auth/hto/*`
and `/admin/hto-operators/*` paths, request and response field names, status
codes, JWT audience, and error codes remain unchanged so current dashboard
clients and all US-04 acceptance criteria continue to work without migration.

---

## 7.18 Amendment — US-03 Family Contact Nomination Delivery

`POST /me/family-contact` and `PATCH /me/family-contact` accept the same local
Nigerian mobile-number format as pilgrim signup, persist it in E.164 form, and
derive ownership exclusively from the authenticated pilgrim access token.
There is no family-contact confirmation or authentication flow.

The Meta WhatsApp template is dispatched through the internal notification
abstraction after the nomination is committed. Successful delivery sets
`notified_of_nomination = true`. If Meta is unavailable, the API returns
`notification_unavailable` while retaining the contact with the flag false;
PATCHing the same number retries the missing notification. Changing the number
resets the flag and notifies the new contact, while name-only edits do not send
duplicate messages. A second POST returns `family_contact_exists`; clients use
PATCH for AC-03.3 updates.

---

## 7.19 Amendment — US-07 Pilgrim Activation Contract

`GET /activation/{activation_code}` is deliberately unauthenticated — Flow B
in `frontend-mobile.md` §8.2 opens straight to the Activation Code Entry
screen from a deep link, before the pilgrim has signed in at all, and needs
enough to reassure them (their HTO's name, the tier) without waiting on
OTP/PIN first. It never returns pilgrim-identifying fields (name, phone,
passport) — only what an HTO operator and tier name reveal, which is no more
sensitive than what the WhatsApp message itself already said (AC-07.2). An
unknown code 404s; a known-but-already-used-or-expired code still 200s with
`valid: false` and a `reason`, so the client can show a specific message
("already used" vs. a hard error) rather than treating every non-2xx the same
way.

`POST /me/activation/redeem` is the single endpoint behind both AC-07.4 and
AC-07.5 — the backend does not distinguish "new" from "existing" pilgrim.
Both are just an authenticated pilgrim with a code: a new pilgrim gets there
by completing OTP + PIN first (the account now exists, the access token is
already issued), an existing pilgrim gets there already signed in. "OTP → PIN
→ package auto-attached" (AC-07.4) describes client-side sequencing, not a
different server contract — the mobile client calls redeem once it has both
a token and the code, regardless of which path produced the token.

Redemption enforces that the authenticated pilgrim's phone number matches the
`manifest_pilgrims` row the code was issued for (both E.164) — a code
delivered to one WhatsApp number should not be redeemable by a different
account, even if that account somehow obtains the code string. This isn't a
documented acceptance criterion but follows directly from AC-07.1's delivery
model; see `data-model.md` §6.15.

There is no endpoint for *generating* an activation code here — that's
`POST /admin/manifest-orders/{order_id}/confirm-payment`'s job (§7.10,
`prd.md` §5.2's "provisioning" step, `data-model.md` §6.14), which sets
`activation_code`/`activation_code_expires_at` per pilgrim once payment is
confirmed. This endpoint only redeems what that flow already produced —
`ActivationService.redeem` reads the tier via
`manifest_pilgrims.manifest_order_id → manifest_orders.pricing_tier_id`, not
a denormalized copy on `manifest_pilgrims` itself.

---

## 7.20 Amendment — US-17 Package Status Snapshot Totals

US-17 review found that `GET /packages/{id}/status` exposed only remaining
data and PSTN minutes even though AC-17.3 requires the Home screen to compare
data remaining with the amount purchased. A client that first observed an
already-consumed package could not reconstruct that denominator correctly;
treating the first observed remainder as 100% produced false healthy states.

The response now includes `data_gb_total` and `pstn_minutes_total`, using the
existing immutable purchase-time snapshot columns on `packages` documented in
`data-model.md` §6.3/§6.29. No new table or column is introduced. Data warning
state is computed as `data_gb_remaining / data_gb_total < 20%`; voice warning
state remains the separate absolute rule `pstn_minutes_remaining < 5` from
AC-17.3. Both reach the red exhausted state at zero.

---

## 7.21 Amendment — US-20 HTO Provisioning Report

**Supersedes a pre-existing spec discrepancy, flagged explicitly rather
than silently overwritten:** §7.8 previously sketched
`GET /hto/manifests/{id}/report?format=csv` as a placeholder, with a
mandatory manifest in the path and an async 202/`job_id` escape hatch
for large manifests. That shape predates this implementation and was
never referenced anywhere else in `/docs` (checked: not in
`testing-qa.md`, `data-model.md`, or `frontend-dashboard.md`) or built
against. It doesn't fit AC-20.3 as written — "filterable by manifest
**and date range**" reads as an optional filter over a
cross-manifest report, not a report that only ever exists scoped to
one manifest by URL. The real endpoint is
`GET /hto/reports/provisioning.csv`, with `manifest_id` as an
*optional* query parameter (omitted = every one of the operator's
manifests) alongside `date_from`/`date_to`. The async/`job_id` path is
dropped: AC-20.4's own 500-row/30s ceiling was measured for real (not
assumed) at ~0.1s server-side generation time against a real Postgres
database (`tests/test_provisioning_report_performance_postgres.py`),
so a synchronous response comfortably clears the bar with no queue
infrastructure needed.

**Row scope:** a pilgrim only appears once their `manifest_order` has
reached `ManifestOrderStatus.PROVISIONED` — `data-model.md` §6.14
defines that status as "every selected pilgrim has a delivered
activation link," i.e. genuinely provisioned. Pilgrims still
`awaiting_payment`/`paid`/`provisioning` are excluded; this is a
*provisioning* report, not a manifest roster (that's already
`GET /hto/pilgrims`, §7.8).

**"Purchase date" (AC-20.2) and the date-range filter (AC-20.3):**
`manifest_orders.payment_confirmed_at` — the only per-pilgrim date this
report has, since HTO packages are purchased at the order level, not
per pilgrim (`data-model.md` §6.14). The date-range filter applies to
this field.

**Check-in count / SOS events (AC-20.2):** lifetime totals for the
pilgrim's linked user account, not scoped to the date-range filter —
a check-in the week after a June-dated purchase still counts toward
that pilgrim's row even if the report itself is filtered to June.
eSIM status reuses the exact same rank/precedence logic as
`GET /hto/pilgrims` (§7.8, `app/esim/service.py`
`HtoPilgrimService.list_pilgrims`) so the two surfaces never disagree
about the same pilgrim's status.

**Cross-tenant isolation:** identical pattern to `GET /hto/pilgrims` —
scoped at the query level via `Manifest.organization_id`, not at the
UI layer; verified with a negative test
(`test_cross_tenant_isolation_one_hto_cannot_see_another_hto_report_data`)
that one operator cannot pull another's rows even by guessing the
other's `manifest_id` directly in the query string.

**Frontend doc gap, flagged not guessed past:** `frontend-dashboard.md`
lists "Reports" as Screen 12 in the §9.1 inventory but had zero
per-screen specification — no data/elements/states section, the same
category of gap `frontend-mobile.md`'s Screen 17 had before US-11. A
minimal per-screen spec has been added to `frontend-dashboard.md` §9.3
covering the assumptions made (manifest selector, date-range picker,
"Download CSV" button, loading state for the generation window).

---

## 7.22 Amendment — US-13 Destination-Keyed Arrival Geofence

`GET /packages/{id}/geofence` adds the package-owned configuration read used
before Android geofence registration. It follows the existing package-status
authorization contract: authentication is required, another user's package is
indistinguishable from a missing package (`package_not_found`, 404), and the
server derives the destination from `packages.destination_country` rather than
trusting a client-supplied country. The response contains `latitude`,
`longitude`, `radius_meters`, and a stable `request_id` for the native geofence.

Only SA is configured for MVP, using US-13's existing Jeddah values. An
unconfigured destination returns `destination_geofence_not_configured` (404),
with no silent fallback to SA. iOS native geofencing remains a pre-existing
platform-completeness gap and is explicitly outside this destination-
abstraction amendment; AC-13.7's permission-free date banner remains the
reliable cross-platform trigger.
