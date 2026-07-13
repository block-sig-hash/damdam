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

POST   /auth/hto/login
  Body: { email, password }
  200: { access_token, refresh_token, operator: {..} }
  403: { error: "pending_approval" | "rejected" }
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

POST   /me/family-contact
  Auth required
  Body: { phone_number: string, name?: string }
  201: { id, phone_number, notified_of_nomination: bool }

PATCH  /me/family-contact
  Auth required
  Body: { phone_number?: string, name?: string }
  200: { ...updated contact }

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

POST   /packages/purchase
  Auth required
  Body: { pricing_tier_id: string, group_size?: int }
  200: { package_id, processor: "paystack"|"flutterwave",
          processor_reference, checkout_url }
  400: { error: "invalid_group_size" }
  Note: `processor` and `checkout_url` are generic — Paystack is
  used unless its checkout initialization call fails, in which
  case the backend falls back to Flutterwave automatically before
  this response is returned. See `data-model.md` §6.7. The client
  never needs processor-specific logic; it opens `checkout_url` in
  a web view regardless of which processor issued it.

GET    /packages/{id}/status
  Auth required
  200: { status: "pending"|"active"|"expired",
          data_gb_remaining, pstn_minutes_remaining }
  Used by the checkout success-screen polling fallback (§5.3
  failure mode in prd.md)

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
```

---

## 7.5 Voice / Calling

**⚠ Vendor status: provisional, not final.** The endpoints below
are written against Twilio's specific API shapes (TwiML
applications, Access Tokens, Twilio Verify) because that's what was
available to spec against first — not because Twilio has won a
final vendor decision. `prd.md` §6's Phase 0 explicitly calls for
quoting both Twilio and Telnyx for the Nigeria/Saudi Arabia
corridors specifically, since PSTN termination is the single
largest variable cost in the margin model and Telnyx's carrier-
owned network structurally tends to be cheaper on exactly this kind
of route. If Telnyx wins that comparison, this section needs a real
amendment (Telnyx uses a Call Control API, not TwiML — a different
shape, not a find-and-replace), not a silent vendor-name swap. Treat
the endpoints below as the *pattern* to follow, not a Twilio lock-in.

```
POST   /voice/token
  Auth required
  200: { token: string, identity: string, expires_at }
  Short-lived Twilio Access Token for the Voice SDK
  (cross-platform — same endpoint serves iOS and Android)

POST   /webhooks/twilio/voice
  Twilio-signed webhook, not user-facing
  TwiML response, sets callerId from verified_cli lookup

POST   /webhooks/twilio/call-status
  Twilio-signed webhook
  Body: Twilio call status payload
  200: (writes call_log, triggers balance deduction)

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
  Body: multipart CSV file
  200: { total_rows, valid_rows, invalid_rows: [{ row_number,
          reason }], preview: [{..valid rows}] }

POST   /hto/manifests/{id}/confirm
  HTO auth required
  200: { status: "validated", pilgrim_count: int }

POST   /hto/manifests/{id}/group
  HTO auth required
  Body: { manifest_pilgrim_ids: [uuid], group_size: int }
  Groups selected (unordered) rows under a shared family_group_id
  for a Family-tier purchase (data-model.md §6.4)
  200: { family_group_id: uuid }

POST   /hto/manifests/{id}/order
  HTO auth required
  Body: { pricing_tier_id: string, manifest_pilgrim_ids: [uuid] }
  Explicit pilgrim selection required — a manifest can have
  multiple orders across different tiers/groupings
  (data-model.md §6.5). manifest_pilgrim_ids must all currently
  have manifest_order_id = NULL.
  200: { manifest_order_id, total_ngn, invoice_url }
  400: { error: "pilgrims_already_ordered", pilgrim_ids: [uuid] }

GET    /hto/manifests/{id}/order/{order_id}
  HTO auth required
  200: { status, total_ngn, invoice_url, payment_confirmed_at? }

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
  Query: ?manifest_id=&search=&sort=
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

GET    /hto/manifests/{id}/report
  HTO auth required
  Query: ?format=csv
  200: (file download, or 202 + job_id if generated
        asynchronously for large manifests)
```

---

## 7.9 Webhooks (Inbound, external providers)

```
POST   /webhooks/paystack
  Paystack-signed (HMAC SHA512 header verification)
  Handles: charge.success
  Idempotent on transaction.processor_reference (prd.md §5.3;
  data-model.md §6.7 — field renamed from paystack_reference)

POST   /webhooks/flutterwave
  Flutterwave-signed (verif-hash header verification)
  Handles: charge.completed
  Same idempotency pattern as the Paystack webhook above, on
  transaction.processor_reference — only fires for transactions
  where processor = 'flutterwave' (data-model.md §6.7's automatic
  fallback path)

POST   /webhooks/twilio/voice        (see §7.5)
POST   /webhooks/twilio/call-status  (see §7.5)

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
POST   /admin/hto-operators/{id}/approve
POST   /admin/hto-operators/{id}/reject
  Body: { reason: string }  (reject only)

GET    /admin/manifest-orders
  Query: ?status=awaiting_payment&search=
  200: { orders: [{ id, hto_business_name, manifest_name,
          total_ngn, invoice_url, days_pending }] }

POST   /admin/manifest-orders/{id}/confirm-payment
  200: { status: "provisioning" }
  Triggers the background provisioning job (data-model.md §6.5)

GET    /admin/sos-notifications/failed
  200: { notifications: [{ id, pilgrim_name, channel,
          failure_reason, sos_timestamp, retry_count }] }

POST   /admin/sos-notifications/{id}/retry
POST   /admin/sos-notifications/retry-bulk
  Body: { notification_ids: [uuid] }

GET    /admin/device-compatibility-log
  Query: ?esim_supported=false&platform=ios
  Used to build the "known incompatible devices" list
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

The admin endpoints above are surfaced through 4 bare-bones
screens in the shared HTO/Admin Next.js dashboard (not a raw API
tool) — see frontend-dashboard.md §9.1, Screens 13–17:

1. **HTO Operator Approvals** — `/admin/hto-operators/*`
2. **Manifest Payment Confirmation** — `/admin/manifest-orders/*`
   (highest-traffic admin screen pre-Hajj-season; needs
   search/filter by HTO name from day one)
3. **Failed Notification Queue** — `/admin/sos-notifications/*`
   (includes bulk retry, given a systemic outage could produce
   many failed rows at once)
4. **Device Compatibility Log** — `/admin/device-compatibility-log`
   (read-only, now filterable by platform)

Auth: `admin_users` table with role-based route guards in Next.js
middleware, same JWT-scope pattern (`aud: admin`) as the HTO
dashboard's `aud: hto_dashboard` distinction — both dashboards
share one Next.js codebase with role-conditional routing.

Explicitly not in the admin UI for MVP: user search/lookup, manual
package editing, refund processing, analytics dashboards. Anything
outside these four screens is a direct database action for MVP,
acceptable given expected pilot volume.

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
