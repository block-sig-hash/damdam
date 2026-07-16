# Data Model
# DamDam — Version 0.1

Database: PostgreSQL 16. ORM: SQLModel (Pydantic + SQLAlchemy). All
primary keys are UUIDv4 unless noted. All tables have `created_at`
and `updated_at` timestamps (omitted below except where
behaviourally relevant).

---

## 6.1 Entity Overview

```
User (pilgrim)
  ├── has one → CallerIdVerification
  ├── has one → FamilyContact
  ├── has many → Package
  ├── has many → EsimProfile (via Package)
  ├── has many → CheckIn
  ├── has many → SosAlert
  ├── has many → CallLog
  ├── belongs to → ManifestPilgrim (nullable, if HTO-sourced)
  └── has many → RefreshToken

Organization
  ├── has many → Manifest
  └── has many → OrganizationRefreshToken

Manifest
  ├── belongs to → Organization
  ├── has many → ManifestPilgrim
  └── has many → ManifestOrder        (see §6.5 — was one-to-one, now one-to-many)

ManifestPilgrim
  ├── belongs to → Manifest
  ├── belongs to → ManifestOrder (nullable — set once ordered, see §6.5)
  ├── has one → User (nullable until activated)
  └── has one → ActivationCode

ManifestOrder
  ├── belongs to → Manifest
  └── has one → Invoice

Package
  ├── belongs to → User
  ├── belongs to → PricingTier
  ├── has one → EsimProfile
  └── has many → Transaction

EsimProfile
  ├── belongs to → Package
  └── has many → UsagePoll

CheckIn
  └── belongs to → User

SosAlert
  ├── belongs to → User
  └── has many → SosNotification

CallLog
  └── belongs to → User

FamilyContact
  └── belongs to → User

Transaction
  ├── belongs to → Package (nullable)
  └── belongs to → ManifestOrder (nullable)

PricingTier
  └── has many → Package

DailyPriceCache
  └── belongs to → PricingTier

DeviceCompatibilityLog
  └── belongs to → User (nullable)
```

---

## 6.2 Table Definitions

### `users` (Pilgrim)

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| phone_number | VARCHAR(14) | UNIQUE, NOT NULL | E.164 format |
| first_name | VARCHAR(100) | NOT NULL | |
| last_name | VARCHAR(100) | NOT NULL | |
| email | VARCHAR(255) | NULLABLE | Optional for Path A; used for receipts |
| pin_hash | VARCHAR(255) | NULLABLE | bcrypt hash; null until PIN set |
| pin_failed_attempts | INTEGER | DEFAULT 0 | Resets on success |
| pin_locked_until | TIMESTAMPTZ | NULLABLE | |
| account_source | ENUM | NOT NULL | `direct` \| `hto_manifest` |
| verified_cli | BOOLEAN | DEFAULT FALSE | True once the account-setup OTP ownership check succeeds through `caller_id_verifications` (`termii` or `twilio`) |
| departure_date | DATE | NULLABLE | Drives the eSIM banner timing |
| destination_country | VARCHAR(2) | DEFAULT 'SA' | ISO code; hardcoded SA for MVP |
| platform | ENUM | NOT NULL | `ios` \| `android` — set at registration |
| status | ENUM | DEFAULT 'active' | `active` \| `suspended` |
| last_login_at | TIMESTAMPTZ | NULLABLE | |

**Indexes:** `phone_number` (unique), `departure_date`

---

### `emergency_content` — removed, see §6.20

This table was designed here ahead of US-12's final acceptance criteria
and was never migrated or implemented. §6.20 supersedes it: the content
it would have held (DamDam's support WhatsApp number, the Arabic
phrasebook) ships as static app-bundled constants instead, per AC-12.3.
The one note that still holds — the HTO operator's number is pulled live
from the pilgrim's assigned `organizations` row, not stored as content —
is carried forward in §6.20.

---

### `caller_id_verifications`

**Design note:** Kept provider-agnostic to match the OTP failover
in §5.1 — the CLI-verification OTP may succeed via either the
primary or secondary OTP provider, and this table records which
one, rather than hardcoding a single vendor's identifier field.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, UNIQUE | One per user |
| otp_provider | ENUM | NOT NULL | `termii` \| `twilio` — whichever provider actually delivered this verification |
| provider_reference | VARCHAR(64) | NOT NULL | Opaque verification ID/SID from whichever provider succeeded |
| verified_at | TIMESTAMPTZ | NOT NULL | |

### `refresh_tokens`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | JWT `jti` |
| user_id | UUID | FK → users, NOT NULL | |
| token_hash | VARCHAR(64) | UNIQUE, NOT NULL | SHA-256; plaintext is never stored |
| expires_at | TIMESTAMPTZ | NOT NULL | |
| revoked_at | TIMESTAMPTZ | NULLABLE | Set when rotated or explicitly revoked |

**Indexes:** `token_hash` (unique), `user_id`, `expires_at`

---

### `family_contacts`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, UNIQUE | One per pilgrim for MVP |
| phone_number | VARCHAR(14) | NOT NULL | E.164 |
| name | VARCHAR(100) | NULLABLE | |
| notified_of_nomination | BOOLEAN | DEFAULT FALSE | True only after Meta accepts the nomination template |

---

### `organizations`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| org_type | ENUM | NOT NULL | `hto_operator` \| `enterprise` \| `government` |
| name | VARCHAR(255) | NOT NULL | Business or organization name |
| primary_contact_name | VARCHAR(100) | NOT NULL | Current HTO API field: `operator_name` |
| email | VARCHAR(255) | UNIQUE, NOT NULL | |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt |
| phone_number | VARCHAR(14) | NOT NULL | |
| nahcon_licence_number | VARCHAR(50) | NULLABLE | Required only when `org_type = hto_operator`; must otherwise be null (`ck_organizations_hto_licence` check constraint) |
| email_verified | BOOLEAN | DEFAULT FALSE | |
| approval_status | ENUM | DEFAULT 'pending' | `pending` \| `approved` \| `rejected` |
| approved_at | TIMESTAMPTZ | NULLABLE | |
| approved_by | UUID | FK → admin_users, NULLABLE | |
| approval_email_sent_at | TIMESTAMPTZ | NULLABLE | Set after the approval email is delivered |
| approval_whatsapp_sent_at | TIMESTAMPTZ | NULLABLE | Set after the approval WhatsApp message is delivered |
| rejected_at | TIMESTAMPTZ | NULLABLE | See §6.17 |
| rejected_by | UUID | FK → admin_users, NULLABLE | See §6.17 |
| rejection_reason | VARCHAR(500) | NULLABLE | See §6.17 |

---

### `manifests`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| organization_id | UUID | FK → organizations | Owning HTO organization for MVP |
| name | VARCHAR(255) | NULLABLE | e.g. "Flight NAF203 — 14 May" |
| status | ENUM | DEFAULT 'draft' | `draft` \| `validated` \| `partially_ordered` \| `provisioned` — see §6.5 |
| total_rows | INTEGER | DEFAULT 0 | |
| valid_rows | INTEGER | DEFAULT 0 | |
| uploaded_file_url | VARCHAR(500) | NULLABLE | R2 object URL, original CSV |
| created_at | TIMESTAMPTZ | NOT NULL | Upload batch creation time |

---

### `manifest_pilgrims`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| manifest_id | UUID | FK → manifests | |
| first_name | VARCHAR(100) | NOT NULL | |
| last_name | VARCHAR(100) | NOT NULL | |
| phone_number | VARCHAR(14) | NOT NULL | |
| passport_number | VARCHAR(50) | NULLABLE | Consider column-level encryption — see security.md §10.4 |
| seat_number | VARCHAR(10) | NULLABLE | |
| row_number | INTEGER | NOT NULL | Original CSV row, for error reference |
| validation_status | ENUM | NOT NULL | `valid` \| `invalid` \| `duplicate_warning` |
| validation_error | VARCHAR(255) | NULLABLE | |
| family_group_id | UUID | NULLABLE | Groups rows for a shared Family package (§6.4) |
| manifest_order_id | UUID | FK → manifest_orders, NULLABLE | Set once included in a placed order; deletion is restricted (§6.5) |
| user_id | UUID | FK → users, NULLABLE | Set once pilgrim activates |
| activation_code | VARCHAR(8) | UNIQUE, NULLABLE | Generated post-payment |
| activation_code_used | BOOLEAN | DEFAULT FALSE | |
| activation_code_expires_at | TIMESTAMPTZ | NULLABLE | 30 days from generation |
| activation_link_sent_at | TIMESTAMPTZ | NULLABLE | Delivery checkpoint for retry-safe WhatsApp activation (§6.14) |
| esim_incompatible_flag | BOOLEAN | DEFAULT FALSE | Set post-activation from device check |

**Indexes:** `manifest_id`, `phone_number`, `activation_code`
(unique), `manifest_order_id`

---

### `manifest_orders`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| manifest_id | UUID | FK → manifests | **No longer UNIQUE** — a manifest may have many orders (§6.5) |
| pricing_tier_id | UUID | FK → pricing_tiers | |
| pilgrim_count | INTEGER | NOT NULL | Count of pilgrims in *this* order |
| wholesale_price_ngn | DECIMAL(12,2) | NOT NULL | Per-pilgrim rate at time of order |
| total_ngn | DECIMAL(12,2) | NOT NULL | |
| status | ENUM | DEFAULT 'awaiting_payment' | `awaiting_payment` \| `paid` \| `provisioning` \| `provisioned` |
| invoice_url | VARCHAR(500) | NULLABLE | Authenticated API download URL |
| invoice_object_key | VARCHAR(500) | NULLABLE | Internal key in the configured S3-compatible or filesystem store |
| invoice_email_sent_at | TIMESTAMPTZ | NULLABLE | Delivery checkpoint for retry-safe invoice email |
| payment_confirmed_at | TIMESTAMPTZ | NULLABLE | |
| payment_confirmed_by | UUID | FK → admin_users, NULLABLE | Manual confirmation for MVP |
| provisioning_enqueued_at | TIMESTAMPTZ | NULLABLE | Background-job dispatch checkpoint |
| created_at | TIMESTAMPTZ | NOT NULL | Used for pending-payment age and admin review ordering |

---

### `pricing_tiers`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| name | VARCHAR(50) | NOT NULL | `Starter` \| `Basic` \| `Standard` \| `Family` |
| usd_reference_price | DECIMAL(10,2) | NOT NULL | Canonical price — see §6.4 for Family tier semantics |
| data_gb | INTEGER | NOT NULL | |
| pstn_minutes | INTEGER | NOT NULL | |
| is_group_tier | BOOLEAN | DEFAULT FALSE | TRUE only for Family (§6.4) |
| min_group_size | INTEGER | NULLABLE | e.g. 2, only set if is_group_tier |
| max_group_size | INTEGER | NULLABLE | e.g. 8, only set if is_group_tier |
| wholesale_usd_price | DECIMAL(10,2) | NOT NULL | HTO channel price (per-person for Family) |
| active | BOOLEAN | DEFAULT TRUE | |
| ngn_price | DECIMAL(12,2) | NOT NULL | Current retail Naira price, per-unit (per-person for Family); admin-editable — see §6.16 |

---

### `pricing_tier_price_changes`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| pricing_tier_id | UUID | FK → pricing_tiers, ON DELETE CASCADE | |
| admin_id | UUID | FK → admin_users, NOT NULL | |
| old_ngn_price | DECIMAL(12,2) | NOT NULL | |
| new_ngn_price | DECIMAL(12,2) | NOT NULL | |
| changed_at | TIMESTAMPTZ | NOT NULL | |

**Indexes:** `pricing_tier_id` — see §6.16

---

### `packages`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users | |
| pricing_tier_id | UUID | FK → pricing_tiers | |
| source | ENUM | NOT NULL | `retail` \| `hto_manifest` |
| status | ENUM | DEFAULT 'active' | `pending` (retail checkout only) \| `active` \| `expired` \| `cancelled` |
| group_size | INTEGER | DEFAULT 1 | Number of pilgrims covered by this purchase (§6.4) |
| data_gb_total | INTEGER | NOT NULL | Snapshot at purchase time |
| data_gb_remaining | DECIMAL(6,2) | NOT NULL | |
| pstn_minutes_total | INTEGER | NOT NULL | Snapshot at purchase time |
| pstn_minutes_remaining | DECIMAL(6,2) | NOT NULL | |
| purchased_at | TIMESTAMPTZ | NOT NULL | |
| expires_at | TIMESTAMPTZ | NULLABLE | Trip-duration based |

**Indexes:** `user_id`

---

### `transactions`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| package_id | UUID | FK → packages, NULLABLE | |
| manifest_order_id | UUID | FK → manifest_orders, NULLABLE | |
| processor | ENUM | NOT NULL, DEFAULT 'paystack' | `paystack` \| `flutterwave` — see §6.7 amendment |
| processor_reference | VARCHAR(100) | UNIQUE, NULLABLE | Idempotency key (Path A); replaces the earlier Paystack-only `paystack_reference` field |
| amount_ngn | DECIMAL(12,2) | NOT NULL | |
| payment_method | ENUM | NULLABLE | `card` \| `bank_transfer` \| `ussd` \| `invoice` |
| status | ENUM | NOT NULL | `pending` \| `success` \| `failed` |
| webhook_payload | JSONB | NULLABLE | Raw processor payload (Paystack or Flutterwave), audit trail |
| receipt_sent_at | TIMESTAMPTZ | NULLABLE | Set after all applicable receipt channels succeed; permits safe retry after a notification outage |

**Indexes:** `processor_reference` (unique, partial index `WHERE
processor_reference IS NOT NULL`)

---

### `esim_profiles`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| package_id | UUID | FK → packages, UNIQUE | |
| aggregator | ENUM | NOT NULL | `monty_mobile` \| `esim_access` \| `1global` — see §6.6 for the final primary/secondary/tertiary ranking and why a three-way redundancy decision, not just vendor-shopping |
| iccid | VARCHAR(22) | NOT NULL | |
| activation_code_lpa | VARCHAR(255) | NOT NULL | LPA string |
| qr_code_url | VARCHAR(500) | NOT NULL | R2 object URL |
| status | ENUM | DEFAULT 'issued' | `issued` \| `downloaded` \| `activated` |
| downloaded_at | TIMESTAMPTZ | NULLABLE | |
| activated_at | TIMESTAMPTZ | NULLABLE | |

---

### `usage_polls`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| esim_profile_id | UUID | FK → esim_profiles | |
| polled_at | TIMESTAMPTZ | NOT NULL | |
| data_used_gb | DECIMAL(6,2) | NOT NULL | Cumulative, from aggregator |
| poll_success | BOOLEAN | NOT NULL | |

**Indexes:** `esim_profile_id`, `polled_at` — subject to the 30-day
raw / daily-summary retention policy, see security.md §10.3

---

### `check_ins`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users | |
| client_generated_id | UUID | UNIQUE, NOT NULL | Set on-device; offline-retry idempotency key |
| timestamp | TIMESTAMPTZ | NOT NULL | Client-side event time |
| latitude | DECIMAL(9,6) | NULLABLE | |
| longitude | DECIMAL(9,6) | NULLABLE | |
| received_at | TIMESTAMPTZ | NOT NULL | Server receipt time |

**Indexes:** `user_id`, `client_generated_id` (unique)

---

### `check_in_notifications`

One row per check-in that has a nominated family contact. This is the durable
WhatsApp-delivery checkpoint and SMS-fallback decision record for AC-15.10.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| check_in_id | UUID | FK → check_ins, UNIQUE, NOT NULL | One notification lifecycle per idempotent check-in |
| whatsapp_status | ENUM | DEFAULT `pending` | `pending` \| `accepted` \| `delivered` \| `failed` |
| whatsapp_message_id | VARCHAR(255) | UNIQUE, NULLABLE | Meta `wamid` used to correlate delivery-status webhooks |
| whatsapp_attempted_at | TIMESTAMPTZ | NULLABLE | |
| whatsapp_delivered_at | TIMESTAMPTZ | NULLABLE | Prevents the scheduled SMS fallback |
| whatsapp_failure_reason | VARCHAR(255) | NULLABLE | Sanitized provider failure |
| fallback_due_at | TIMESTAMPTZ | NULLABLE | Accepted time + configured 60-second window; immediate on send failure |
| sms_status | ENUM | NULLABLE | `sent` \| `failed`; null until fallback attempted |
| sms_message_id | VARCHAR(255) | NULLABLE | Configured SMS provider reference (Termii for MVP) |
| sms_fallback_sent_at | TIMESTAMPTZ | NULLABLE | Idempotent fallback checkpoint |
| sms_failure_reason | VARCHAR(255) | NULLABLE | Sanitized provider failure |
| sms_attempt_count | INTEGER | DEFAULT 0 | Failed fallback attempts; capped at three |
| admin_queued_at | TIMESTAMPTZ | NULLABLE | Set after the third SMS failure for operational follow-up |
| created_at | TIMESTAMPTZ | NOT NULL | |

**Indexes:** `check_in_id` (unique), `whatsapp_message_id` (unique),
`fallback_due_at`

---

### `sos_alerts`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users | |
| client_generated_id | UUID | UNIQUE, NOT NULL | |
| timestamp | TIMESTAMPTZ | NOT NULL | |
| latitude | DECIMAL(9,6) | NULLABLE | |
| longitude | DECIMAL(9,6) | NULLABLE | |
| status | ENUM | DEFAULT 'active' | `active` \| `resolved` \| `cancelled` |
| resolved_at | TIMESTAMPTZ | NULLABLE | |
| resolved_by | UUID | FK → organizations, NULLABLE | |

**Indexes:** `user_id`, `status`

---

### `sos_notifications`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| sos_alert_id | UUID | FK → sos_alerts | |
| channel | ENUM | NOT NULL | `push` \| `email` \| `whatsapp_operator` \| `whatsapp_family` \| `sms_family` — see §6.27 |
| event | ENUM | DEFAULT 'triggered' | `triggered` \| `cancelled`; keeps cancellation follow-up delivery independently auditable |
| status | ENUM | DEFAULT 'pending' | `pending` \| `sent` \| `failed` |
| sent_at | TIMESTAMPTZ | NULLABLE | |
| failure_reason | VARCHAR(255) | NULLABLE | |
| retry_count | INTEGER | DEFAULT 0 | Failed channel attempts; capped at three before admin queue |
| whatsapp_message_id | VARCHAR(255) | UNIQUE, NULLABLE | `whatsapp_family` only — Meta `wamid`, correlates the delivery webhook shared with check-in (§6.27) |
| whatsapp_delivered_at | TIMESTAMPTZ | NULLABLE | `whatsapp_family` only — set by the Meta webhook; suppresses the SMS fallback if present before `fallback_due_at` |
| fallback_due_at | TIMESTAMPTZ | NULLABLE | `whatsapp_family` only — accepted time + configured window, or immediate on outright send failure |
| admin_queued_at | TIMESTAMPTZ | NULLABLE | Set after the third failed attempt |
| created_at | TIMESTAMPTZ | NOT NULL | |

One row per channel per SOS event — allows the admin failed-
notification queue to retry only the failed channel. `sms_family` rows
are the one exception: created lazily by the fallback, not eagerly with
the other four (§6.27).

**Unique constraint:** `(sos_alert_id, channel, event)`, `whatsapp_message_id` (unique, nullable)

---

### `call_logs`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users | |
| telnyx_call_leg_id | VARCHAR(64) | UNIQUE, NOT NULL | Stable Telnyx call-leg correlation ID; `call_control_id` remains the command token and is not persisted as identity |
| direction | ENUM | NOT NULL | `outbound` only for MVP |
| call_type | ENUM | NOT NULL | `pstn` \| `app_to_app` |
| to_number | VARCHAR(14) | NULLABLE | Recipient Nigerian number for PSTN and app-to-app history; nullable only when a provider event lacks a resolvable destination |
| duration_seconds | INTEGER | NOT NULL | |
| pstn_minutes_charged | DECIMAL(6,2) | DEFAULT 0 | 0 for app-to-app |
| started_at | TIMESTAMPTZ | NOT NULL | |
| ended_at | TIMESTAMPTZ | NULLABLE | |

**Indexes:** `user_id`, `telnyx_call_leg_id` (unique)

---

### `voice_credentials`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, UNIQUE | One Telnyx identity per pilgrim; app-to-app lookup target |
| telnyx_telephony_credential_id | VARCHAR(64) | UNIQUE, NOT NULL | Server-side credential resource used to mint short-lived JWTs |
| sip_username | VARCHAR(128) | UNIQUE, NOT NULL | Telnyx `gencred…` SIP username used for app-to-app routing and signed-webhook correlation |
| created_at | TIMESTAMPTZ | NOT NULL | |

**Indexes:** `user_id` (unique), `sip_username` (unique)

---

### `device_compatibility_log`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, NULLABLE | |
| event_type | ENUM | NOT NULL, DEFAULT `compatibility_check` | `compatibility_check` \| `issuance_attempt` |
| platform | ENUM | NULLABLE | `ios` \| `android`; required for compatibility checks |
| device_model | VARCHAR(100) | NULLABLE | Required for compatibility checks |
| os_version | VARCHAR(20) | NULLABLE | |
| esim_supported | BOOLEAN | NULLABLE | Required for compatibility checks |
| aggregator | ENUM | NULLABLE | Vendor used for an issuance attempt (§6.6) |
| attempt_succeeded | BOOLEAN | NULLABLE | Set for issuance attempts |
| failure_reason | VARCHAR(255) | NULLABLE | Sanitized vendor failure summary |
| checked_at | TIMESTAMPTZ | NOT NULL | |

Feeds the "known incompatible devices" analytics referenced in
the PRD §5.4 — now tracks platform explicitly given dual-platform
scope, since iOS and Android compatibility failures have different
causes (hardware support vs. API absence) and need different
downstream handling.

---

### `device_tokens`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, NOT NULL, ON DELETE CASCADE | Current signed-in pilgrim |
| fcm_token | VARCHAR(4096) | UNIQUE, NOT NULL | One Firebase app-installation registration |
| platform | ENUM | NOT NULL | `ios` \| `android` |
| updated_at | TIMESTAMPTZ | NOT NULL | Refreshed whenever the client uploads its current token |

**Indexes:** `user_id`; `fcm_token` has a unique constraint (which PostgreSQL
backs with its own unique index).

---

### `admin_users` (internal, minimal for MVP)

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| email | VARCHAR(255) | UNIQUE, NOT NULL | |
| password_hash | VARCHAR(255) | NOT NULL | |
| role | ENUM | DEFAULT 'admin' | Single role for MVP, kept extensible — see security.md §10.5 |

---

## 6.3 Key Design Decisions Worth Flagging

**Offline-first idempotency (`client_generated_id`):** Both
`check_ins` and `sos_alerts` use a client-generated UUID as the
deduplication key, not the server-assigned primary key. This is
what makes the offline queue safe to retry indefinitely without
creating duplicate check-ins if a request succeeds server-side but
the response is lost on a spotty connection.

**`manifest_pilgrims` vs `users`:** Deliberately separate tables. A
row in `manifest_pilgrims` represents an *intended* pilgrim from an
HTO's CSV upload — it may never convert to a `users` row if the
pilgrim never activates. This keeps unregistered manifest data out
of the core user table and makes the HTO's "who hasn't activated
yet" view a simple query (`manifest_pilgrims WHERE user_id IS
NULL`).

**Snapshot fields on `packages`:** `data_gb_total` and
`pstn_minutes_total` are copied from `pricing_tiers` at purchase
time rather than joined live. This protects historical packages
from being altered if tier definitions change later.

**No `family_view` table:** The family contact has no app account
and no login. All communication is one-way outbound (WhatsApp), no
read receipts or two-way state to track.

**`usage_polls` as an append-only log:** Keeps historical poll
results rather than only the latest value, separating "what the
aggregator told us" (immutable fact) from "what we currently
believe the balance is" (derived, on `packages.data_gb_remaining`).

**`platform` field on `users` and `device_compatibility_log`:**
Added for dual-platform scope — lets product analytics and the
admin Device Compatibility screen distinguish iOS vs. Android
failure patterns, which have fundamentally different causes (see
prd.md §5.4).

---

## 6.4 Amendment — Variable Family Group Size

The Family tier is a **per-person rate**, not a fixed bundle.

`pricing_tiers.is_group_tier`, `min_group_size`, `max_group_size`
replace an earlier fixed `pilgrim_count = 4` assumption.
`packages.group_size` records how many pilgrims a specific
purchase covers (buyer-selected, 2–8, constrained by the tier's
min/max).

**Pricing calculation:**
```
family_price_ngn = per_person_ngn_rate × group_size
```

**HTO flow:** `manifest_pilgrims.family_group_id` groups multiple
rows under one Family package purchase — an operator selects N
rows, tags them with a shared `family_group_id`, and purchases one
Family package with `group_size = N` covering all of them.

**UI implication:** Package Selection screen (frontend-mobile.md
§8.3) needs a group-size stepper (2–8) with the price
recalculating live, per PRD AC-08.4.

---

## 6.5 Amendment — Multiple Orders per Manifest

`manifest_orders.manifest_id` is **no longer UNIQUE** — one
manifest can have many orders, since an HTO may want to purchase
individual-tier packages for most pilgrims and separate Family-tier
packages for grouped pilgrims, all from the same uploaded manifest.

`manifest_pilgrims.manifest_order_id` (nullable FK) is what
prevents double-ordering — a pilgrim row belongs to at most one
order. The dashboard's order-placement flow queries for
*unordered* pilgrims (`manifest_order_id IS NULL`) as its
selectable pool.

**`manifests.status = 'provisioned'`** now means "all valid
pilgrims have been included in at least one order," computed as:

```sql
SELECT COUNT(*) FROM manifest_pilgrims
WHERE manifest_id = :id
  AND validation_status = 'valid'
  AND manifest_order_id IS NULL
-- = 0 means fully provisioned
```

See api-spec.md §7.7 for the corresponding endpoint changes and
frontend-dashboard.md §9.3 (Screen 9) for the UI flow this implies.

---

## 6.6 Amendment — Three-Way eSIM Aggregator Redundancy

**This was decided very early in this project's planning, before
this doc suite existed, and never made it into the committed
spec** — `esim_profiles.aggregator` originally listed only `airalo`
and `esim_access`, missing the eventual redundancy vendors
entirely. Fixed here, following the same amendment pattern as
§6.4/§6.5, and now updated again to reflect the final, resolved
ranking (superseding an intermediate eSIM-Access-primary state this
section described in an earlier draft).

**Why a second and third supplier, not just cost-shopping:** the
real justification is redundancy during a concentrated, high-stakes
surge, not marginal price competition. During actual Hajj week,
thousands of pilgrims may attempt eSIM activation within a
compressed window (arrival at Jeddah, a specific prayer time, a
scheduled group movement). If a single eSIM aggregator has a
provisioning outage, an API degradation, or a capacity shortage
during that exact window, there's no fallback — every pilgrim
depending on that provider is affected simultaneously.

**Final ranking: Monty Mobile (primary), eSIM Access (secondary),
1Global (tertiary).** Vendor order is held as configuration
(`ESIM_VENDOR_PRIMARY` / `ESIM_VENDOR_SECONDARY` /
`ESIM_VENDOR_TERTIARY`), not hardcoded, since relative pricing,
coverage, and reliability across the Nigeria/Saudi Arabia corridor
are expected to shift as real usage data comes in. Issuance is
attempted against the primary vendor; on a real issuance failure
(not merely slow — an error response or timeout), the system
automatically cascades to the secondary, then the tertiary, before
falling to retry-with-backoff-then-admin-queue (see `prd.md` §5.4).
Airalo was evaluated during earlier planning but is not one of the
three committed vendors.

**What this does NOT mean:** this is not "pick whichever is
cheapest per request" load-balancing from day one. The three
vendors are ranked, not dynamically selected per-request, until
there's real operational confidence in all three providers'
reliability and provisioning latency under load. Dynamic best-
price/best-performance selection by destination is a reasonable
Phase 2+ optimization once all three integrations are proven, not
an MVP requirement.

**Schema implication beyond the enum change:** no other structural
change is needed — `esim_profiles.aggregator` already existed
specifically to support multiple providers per package, so the
enum values are additive, not a breaking change to any existing
row.

---

## 6.7 Amendment — Flutterwave as a Secondary Payment Processor

`transactions` originally hardcoded a `paystack_reference` field —
fine when Paystack was the only processor, wrong once a second one
exists. Generalized to `processor` (enum) + `processor_reference`
(the actual idempotency key, now processor-agnostic), following the
same abstraction pattern as `esim_profiles.aggregator` (§6.6) and
the `VoiceService`/`ESIMService`/`PaymentService` internal
abstraction principle in `AGENTS.md`.

**Why Flutterwave over Bachs.io, decided explicitly rather than
left open:** Bachs is a subscription/SaaS billing platform built
for global digital-product companies handling proration and
multi-country VAT — solving a problem DamDam doesn't have, not a
Naira-consumer-payment problem it solves better. Bachs's actual
scale, reliability track record, and CBN regulatory standing are
also unverified, a real concern for a system handling real money
from pilgrims before a safety-critical trip. Flutterwave is an
established, credible Nigerian payment processor with a track
record comparable to Paystack's, and — critically — it actually
fits the job: domestic Naira card/transfer/USSD conversion for a
Nigerian consumer, the same category Paystack already serves. No
further Bachs evaluation is planned unless something material
changes.

**Failover trigger logic — automatic, not user-facing:** Paystack
remains primary. If Paystack's checkout initialization call fails
or times out, the backend falls back to Flutterwave transparently
— the pilgrim never sees a "choose your payment provider" screen,
consistent with the "keep it simple for this demographic" principle
already established throughout `prd.md` and `frontend-mobile.md`.
This mirrors the eSIM dual-supplier redundancy reasoning in §6.6:
protection against a single processor's outage during a
concentrated high-volume window (HTOs bulk-purchasing pre-
departure, a marketing push pre-Hajj-season), not price
optimization or user choice.

**What this does NOT mean:** Flutterwave is not dynamically
selected per-transaction, and there's no A/B routing between the
two processors. It exists purely as an automatic fallback path —
Paystack is used for every transaction unless it's actually
unavailable at the moment of checkout.

**API implication:** `POST /packages/purchase`'s response shape
in `api-spec.md` §7.3 needs to change from Paystack-specific field
names to a generic `processor`/`checkout_url` shape — see that
section's amendment note.

---

## 6.8 Amendment — Hashed Refresh-Token Sessions

The initial `users` schema named JWT refresh tokens as sensitive
authentication material in `security.md` §10.4 but omitted the table
needed to store and revoke them. `refresh_tokens` closes that gap for
US-01: only a SHA-256 digest is persisted, tokens are rotated on use,
and a revoked or expired token cannot establish a new session.

This is deliberately a separate one-to-many table rather than fields
on `users`, so one pilgrim can have independent iOS/Android sessions
and one compromised device can be revoked without signing out every
device.

---

## 6.9 Amendment — Organization Dashboard Refresh-Token Sessions

`POST /auth/hto/login` has always returned a refresh token, while the
original `refresh_tokens` table can only reference pilgrim `users`.
`organization_refresh_tokens` closes that mismatch for US-04 using the same
security properties as pilgrim sessions: JWT `jti` primary key,
`organization_id` foreign key, SHA-256 token digest, expiry, and
revocation timestamp. Keeping the tables separate preserves strict
actor typing and prevents an HTO token from being accepted by the
pilgrim refresh path.

### `organization_refresh_tokens`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | JWT `jti` |
| organization_id | UUID | FK → organizations, NOT NULL | |
| token_hash | VARCHAR(64) | UNIQUE, NOT NULL | SHA-256 |
| expires_at | TIMESTAMPTZ | NOT NULL | |
| revoked_at | TIMESTAMPTZ | NULLABLE | |

**Indexes:** `token_hash` (unique), `organization_id`, `expires_at`.

---

## 6.10 Amendment — HTO Approval Notification Delivery State

US-04 sends approval notifications over email and WhatsApp. Because those are
independent external calls, `organizations` records delivery of each channel
separately. Approval is committed before notification dispatch, and a retry
only sends channels whose timestamp is still null. This prevents a successful
email followed by a failed WhatsApp call from rolling the operator back to
`pending` or sending the email twice on retry.

---

## 6.11 Amendment — Generic Organization Identity

The US-04 `hto_operators` table is renamed to `organizations` before US-05/06
add dependent records. The base identity now uses generic `name` and
`primary_contact_name` columns plus a required `org_type` enum. Existing rows
are migrated to `hto_operator`; `enterprise` and `government` are reserved for
future customer types and do not enable any new behavior.

NAHCON licensing remains on the base table as a nullable, type-conditional
field: a check constraint requires it for `hto_operator` organizations and
requires it to be null for other organization types. This keeps the current
HTO read path simple while preventing a Hajj-specific credential from becoming
a required attribute of every future organization.

The same migration renames `hto_refresh_tokens` to
`organization_refresh_tokens`, changes its owner key to `organization_id`, and
renames the existing approval enum and database constraints. The public US-04
HTO API retains its current field names and behavior; this amendment changes
only internal persistence and ownership terminology.

---

## 6.12 Amendment — Family Nomination Delivery State

US-03 uses the existing one-to-one `family_contacts` design. The unique
`user_id` index enforces one contact per pilgrim, and updates mutate that row
rather than replacing it. `notified_of_nomination` is operational delivery
state, not family-contact consent: it remains false when WhatsApp is
unavailable and returns to false whenever the nominated number changes. This
allows a retry to target only an undelivered nomination without duplicating a
message already accepted by Meta.

---

## 6.13 Amendment — US-05 Manifest Staging

US-05 introduces `manifests` and `manifest_pilgrims` against the generic
`organizations` owner key. Upload validation stages every CSV row while the
manifest is `draft`, including invalid rows and duplicate warnings, so the
operator can review an exact row-numbered preview. Confirmation removes invalid
staging rows and advances the batch to `validated`; duplicate-warning rows are
retained because warnings do not block acceptance.

`manifest_order_id` is created as a nullable UUID in this migration so the
US-05 model already exposes the multi-order ownership slot. Its foreign key is
deliberately added by US-06 in the same migration that creates
`manifest_orders`, avoiding a forward reference to a table that does not yet
exist while preserving the §6.5 design.

---

## 6.14 Amendment — US-06 Bulk Manifest Purchasing

US-06 creates `pricing_tiers`, `daily_price_cache`, and `manifest_orders`, then
adds the deferred `manifest_pilgrims.manifest_order_id` foreign key described in
§6.13. The foreign key uses `ON DELETE RESTRICT` so an invoiced pilgrim cannot be
silently returned to the unordered pool by deleting an order.
Because US-05 reserved the nullable UUID before its target table existed, the
migration clears any pre-US-06 non-null staging value before adding the foreign
key; its downgrade also clears those references before removing the order table.

HTO wholesale prices are snapshotted in naira when an order is placed. The
current daily retail price supplies the exchange-rate-adjusted base, while the
tier's canonical retail/wholesale ratio supplies the channel discount:

```text
wholesale_price_ngn = daily_price_cache.ngn_price
                      × pricing_tiers.wholesale_usd_price
                      ÷ pricing_tiers.usd_reference_price
total_ngn = wholesale_price_ngn × pilgrim_count
```

(§6.16 replaces `daily_price_cache.ngn_price` with `pricing_tiers.ngn_price`
as the retail source in this formula; the ratio itself is unchanged.)

The stored prices never change after order creation. Family orders select one
complete pre-grouped set within the tier's 2–8 bounds; non-group tiers accept
only ungrouped pilgrims. The nullable order key and non-unique manifest key
preserve the multi-order pool defined in §6.5.

Invoice PDFs are stored behind an authenticated API download and attached to
the operator email. `invoice_email_sent_at` makes a retry after an email outage
resume the existing order instead of creating or mailing a duplicate; the
order UUID also supplies a stable idempotency key to the email provider.

Manual admin confirmation advances `awaiting_payment → provisioning` before a
background job is dispatched. `provisioning_enqueued_at` makes repeated
confirmation idempotent; an unmarked provisioning order remains visible in the
pending admin queue so dispatch can be retried after a queue outage. The worker
generates 30-day activation codes only after confirmation and records
`activation_link_sent_at` per pilgrim, allowing partial WhatsApp failures to
resume without resending successful deliveries. It marks the order
`provisioned` only after every selected pilgrim has a delivered activation link.

At this pre-activation stage, the selected `manifest_order` tier plus each
linked pilgrim row is the purchased package entitlement. A concrete `packages`
row requires `user_id`, so it is materialized when the pilgrim redeems the code
and the manifest row is linked to an account; payment confirmation never creates
a placeholder user merely to satisfy that foreign key.

---

## 6.15 Amendment — US-07 Redemption Materializes `packages`

`packages` was already specced in §6.2 but had no real table or migration
until US-07 — the only prior consumer of `pricing_tiers` (US-06, §6.14) never
needed to create a `packages` row itself, since a package requires `user_id`
and no `users` row is guaranteed to exist at order-placement or provisioning
time. This migration builds `packages` exactly as already documented in
§6.2, scoped to what redemption needs: it does not add `GET /pricing/tiers`
(US-08) or checkout (US-09) — neither is exercised by an HTO-manifest-sourced
package, since the pilgrim's HTO already paid via §6.14's invoice flow, not
through the app's own retail checkout.

**Tier lookup goes through the real order, not a shortcut.** An earlier draft
of this amendment added an interim `manifest_pilgrims.pricing_tier_id` column
because, at the time, `manifest_orders` didn't exist yet. It now does (§6.14),
with a real `manifest_pilgrims.manifest_order_id` foreign key, so
`ActivationService.redeem` sizes the `packages` row from
`pilgrim.manifest_order_id → manifest_orders.pricing_tier_id` directly — no
denormalized copy of the tier on `manifest_pilgrims` at all.

**Redemption is phone-locked.** `ActivationService.redeem` requires the
authenticated pilgrim's `users.phone_number` to match the target
`manifest_pilgrims.phone_number` exactly (both E.164). The activation code is
delivered by WhatsApp to that specific number (AC-07.1), so this closes an
otherwise-open door: without it, anyone who obtained a valid code (not just
the intended pilgrim) could redeem it under their own account. A single-use
code plus a conditional atomic `UPDATE ... WHERE activation_code_used =
false` (not a plain read-then-write) also closes the race between two
concurrent redemption attempts for the same code — the same pattern §6.14's
provisioning worker uses for its own per-pilgrim WhatsApp delivery checkpoint.

---

## 6.16 Amendment — US-26 Scaled Down to Manual Naira Pricing

US-26 was originally specced as a daily NFEM-indexed FX-cron job writing into
`daily_price_cache` (one dated row per tier per day, with `fx_rate_used` as
its audit trail). Before any of that automation was built, US-26 was scoped
down to a manual, admin-triggered flow (`prd.md` §5.9/§4.10 — see the scope
note there for the full reasoning: Naira has been comparatively stable under
the CBN's reformed NFEM framework, and a live FX dependency is not worth
building for ~1-2% monthly movement pre-launch). `daily_price_cache` was
real and migrated (US-06, §6.14); no production or staging environment
exists yet for it to have been written to there, but local/test databases
can hold real rows in it (seeded by tests or manual exercising of US-06),
so the migration cannot assume the table — or `pricing_tiers` itself — is
empty.

`pricing_tiers.ngn_price` is therefore added nullable first, backfilled
from each tier's most recent `daily_price_cache` row (a correlated
`UPDATE ... FROM (SELECT DISTINCT ON (pricing_tier_id) ...)`), and only
then set `NOT NULL` — so a database with pre-existing tiers keeps their
last-known price instead of the migration failing (or worse, guessing a
default) against unset data. A tier with no `daily_price_cache` history at
all has no principled backfill value; the `NOT NULL` step fails loudly on
purpose in that case rather than defaulting a real money field to zero or
a placeholder. Downgrading recreates `daily_price_cache` as an empty
table (schema only, not a data round-trip), so a downgrade-then-upgrade
sequence relies on this same backfill and will itself hit that failure —
expected, since the downgrade is what discarded the history to backfill
from, not a flaw in the upgrade path against real pre-existing data.

`pricing_tiers` gains a single `ngn_price` column: the current retail Naira
price, admin-editable, replacing the "look up today's dated row" pattern
with a plain in-place value. `_wholesale_price()`'s ratio formula (§6.14) is
unchanged; only where it reads the retail price from changes, per the note
on that formula above. Because every tier now always has exactly one price
by construction (a NOT NULL column, not a query that can return zero rows),
`ManifestOrderService`'s `pricing_unavailable` error path for a missing
price lookup becomes structurally unreachable and was removed from
`list_pricing()` and `place_order()`; `pricing_unavailable` itself is kept
for `_wholesale_price()`'s unrelated `usd_reference_price <= 0` guard and
for `_group_tier()` finding no active group tier, both still-live failure
modes.

`pricing_tier_price_changes` replaces `daily_price_cache` as the audit
trail (AC-26.4): one row per admin-initiated price change, capturing the
admin, old value, new value, and timestamp — an append-only log rather than
a dated snapshot table, since there is no longer a daily write to snapshot.
`admin_id` is a plain (RESTRICT) NOT NULL foreign key to `admin_users`,
unlike `organizations.approved_by`'s nullable/SET NULL pattern (§6.11) —
an audit row's actor is load-bearing here (AC-26.4 requires knowing *who*
changed a price), whereas `approved_by` is informational, so this table
favors always recording a real admin over tolerating admin-account deletion.

No new admin-review gate is introduced: a price update takes effect
immediately (AC-26.2), matching the "manual, on-demand action" framing in
the scope note — the confirmation step (AC-26.3, the %-change display) is a
dashboard-side guardrail before the API call, not a second approval stage.

---

## 6.17 Amendment — US-04 Admin Rejection of HTO Operators

`api-spec.md` §7.10 documented `POST /admin/hto-operators/{id}/reject`
since PR #32, but no route, service method, or schema field ever backed
it — `approve()` was real, `reject()` was not, and `organizations` had no
column to hold a rejection reason. The admin approvals dashboard screen
needs a working reject action, so this amendment builds it for real
rather than against the pre-existing (aspirational) doc.

`rejected_at`/`rejected_by` mirror `approved_at`/`approved_by` exactly
(same nullable-FK-with-SET-NULL pattern, §6.11) for the same reason: an
audit timestamp/actor pair per terminal state. `rejection_reason` is a
plain nullable `VARCHAR(500)`, not a separate audit table like
`pricing_tier_price_changes` (§6.16) — rejection is a one-time terminal
transition per operator (there is no "reject again with a new reason"
scenario the way a price can change repeatedly), so a column on the row
itself is sufficient; there is nothing to accumulate a history of.

`HTOService.reject()` mirrors `approve()`'s transition guard symmetrically:
`approve()` refuses to touch an already-`REJECTED` organization,
`reject()` refuses to touch an already-`APPROVED` one — both raise the
existing `invalid_approval_transition` error, so no new error code was
needed. Unlike `approve()`, `reject()` sends no notification (no AC
requires one, and `prd.md` §4.2's AC-04.5 only covers the approval path);
it commits the terminal state and returns.

---

## 6.18 Amendment — US-09 Retail Payment Materialization

US-09 makes the previously specified `transactions` table real in migration
`0010_us09_retail_payments`. The table uses one globally unique, partial
`processor_reference` index (`WHERE processor_reference IS NOT NULL`) across
both Paystack and Flutterwave. A processor name is therefore audit/routing
metadata, not part of the idempotency key: the first matching success webhook
can transition `pending → success`, and every duplicate becomes a no-op even
when callbacks are retried concurrently.

Retail checkout must return a durable `package_id` before the payment web view
opens, while balances cannot be active before a signed success webhook. The
`package_status` enum therefore gains `pending`, used only for a Path-A retail
package between successful checkout initialization and webhook confirmation.
The package snapshots the selected tier and group size immediately, starts with
zero remaining balances, and is atomically changed to `active` with its full
snapshot balances by the same transaction-status transition that wins the
idempotency race. HTO-manifest redemption remains unchanged and creates an
`active` package directly because its invoice was already confirmed upstream.

`transactions.receipt_sent_at` is a delivery checkpoint rather than a new
payment state. Activation commits before receipt delivery so a Resend or Meta
outage can never roll back a paid package. If delivery fails, a later duplicate
webhook remains a payment no-op but retries only the missing receipt checkpoint;
successful email delivery also uses the processor reference as Resend's
idempotency key.

---

## 6.19 Amendment — US-11 eSIM Issuance Retry State and Attempt Audit

US-11 materializes the already-specified `esim_profiles` table in migration
`0012_us11_esim_profiles`. Its `package_id` unique constraint is the durable
idempotency boundary. The service also locks the owning `packages` row before
calling any supplier, while each supplier receives that package UUID as its
idempotency key; concurrent or repeated taps therefore cannot issue two remote
profiles before the database uniqueness check runs.

`device_compatibility_log` now records two conditional event shapes. Existing
rows are backfilled as `compatibility_check` and keep their platform/device/
support fields. An `issuance_attempt` instead carries `aggregator`,
`attempt_succeeded`, and an optional sanitized failure reason. The original
device fields become nullable only because a server-side supplier attempt has
no device model; compatibility-check writes still require them at the API
schema/service boundary. This reuses the US-10 operational log, as required by
PRD §5.4, rather than creating a second vendor-attempt audit table.

No generic admin work queue existed before US-11. `esim_issuance_jobs` is the
small persistent queue for this lifecycle: unique `package_id`, `attempt_count`,
`next_attempt_at`, `last_error`, `admin_queued_at`, `completed_at`, and
`success_notified_at`. The first all-vendor failure retries after 60 seconds,
the second after 5 minutes, and the third clears automatic scheduling and sets
`admin_queued_at`. Payment and HTO activation commit a due job before asking
Celery to enqueue it, so a broker outage cannot roll back a paid package or
silently lose the provisioning work.

---

## 6.20 Amendment — US-12 Drops the `emergency_content` Table

§6.2's `emergency_content` table (destination-country-keyed, with a JSONB
`phrasebook` and `local_emergency_numbers`) was designed before US-12's
acceptance criteria were finalized. AC-12.3 as shipped is explicit: this
content is "bundled directly in the app, not downloaded separately —
always available offline, zero data cost, no download step, no map SDK
**or content-pack table needed**." A country-keyed table bought future
multi-country flexibility DamDam doesn't have a second market to use yet
(`SA` was always going to be the only populated row for MVP, per that
table's own design note), at the cost of the one thing AC-12.3 actually
asks for: content that's available with *zero* network dependency, not
"available after one successful fetch." A bundled constant is strictly
better than a one-row table for that specific requirement, and the table
was never implemented (no migration, no route, no consumer) — so this
supersedes a design, not a shipped shape.

`emergency_content` is therefore **removed from the schema**. What it
would have held is now:
- **DamDam's support WhatsApp number**: a static constant
  (`apps/mobile/src/config/env.ts`'s `SUPPORT_WHATSAPP_NUMBER`, already
  present as a placeholder ahead of this amendment).
- **The Arabic phrasebook** (help, thank you, where is, I don't
  understand, I need a doctor): a static constant
  (`apps/mobile/src/content/emergencyEssentials.ts`), not JSONB rows.
- **Local emergency numbers** (e.g. police/ambulance): dropped entirely,
  not just moved — `prd.md` §4.4 AC-12.2's current list doesn't include
  them, so this isn't a downgrade from a shipped feature, only from an
  unbuilt table's broader original design.

The one thing the original table's own design note got right stands
unchanged: **the HTO operator's number is still not bundled** — it's
per-pilgrim, not per-country, and is read live from the pilgrim's
assigned `organizations` row via the existing `manifest_pilgrims` →
`manifests` → `organizations` chain (the same join path
`DeviceCompatibilityService` already uses for the US-10 follow-up flag).
`GET /me/emergency-contact` (`api-spec.md` §7.2) is the one new,
narrowly-scoped read for this — it returns only `hto_operator_name`/
`hto_operator_phone_number`, both nullable for a direct/retail pilgrim
with no assigned HTO. If a second destination country is ever onboarded,
reintroducing a country-keyed content table then — when there's an
actual second row to justify it — is the right move, not building it
speculatively now.

---

## 6.21 Amendment — US-13 Push Registration Gap

US-13 requires an opt-in arrival notification but the original model had no
way to associate an FCM app installation with a pilgrim. `device_tokens` is the
minimal missing registration table: a globally unique `fcm_token`, its current
`user_id`, platform, and refresh timestamp. A token is global-unique rather
than only unique per user because one physical app installation must not remain
attached to two accounts when a shared phone signs out and another pilgrim
signs in; uploading it again transfers that installation to the current user.

The table deliberately does not store location history, geofence coordinates,
notification content, or delivery analytics. Jeddah region monitoring remains
on-device and opt-in; the permission-free, date-based activation banner remains
the primary trigger. Firebase recommends refreshing server-side registration
timestamps whenever the client uploads its current registration, which is why
`updated_at` is part of this otherwise-small model.

---

## 6.22 Amendment — US-14 Telnyx Call Identity and Per-User WebRTC Credentials

The original `call_logs.twilio_call_sid` field survived the Phase 0 voice-vendor
decision even though `api-spec.md` §7.5 had already moved the contract to
Telnyx. This is a semantic amendment, not a vendor-name substitution. Telnyx
exposes three related identifiers: `call_control_id` is the opaque token used
to issue commands for a live leg, `call_session_id` groups related legs, and
`call_leg_id` is the stable identifier intended to correlate webhooks for one
leg. `call_logs` therefore persists `telnyx_call_leg_id`; its unique constraint
is also the hangup-webhook billing idempotency boundary. `call_control_id` stays
ephemeral and is used only while issuing dial/bridge/hangup commands.

The table was documentation-only before US-14—no migration had materialized
it—so migration `0014_us14_voice_calling` creates the corrected Telnyx shape
directly. There is no deployed Twilio column requiring data migration.

US-14 also makes the previously implicit client identity explicit through
`voice_credentials`. Telnyx recommends one telephony credential per application
user; sharing one account-wide SIP login would make signed call webhooks
impossible to attribute safely and would couple app-to-app routing to a global
secret. The API creates a per-user credential lazily, stores only its Telnyx
resource ID and SIP username, and returns short-lived JWTs to the app. API keys
and credential-management calls remain server-side.

Finally, `users.verified_cli` is corrected to describe the provider-agnostic
account-setup ownership check already represented by `caller_id_verifications`.
Termii remains primary and Twilio Verify secondary for OTP; neither is the voice
carrier. That flag gates PSTN caller-ID presentation only. An unverified user may
still call another registered DamDam SIP identity for free.

---

## 6.23 Amendment — US-15 Check-In Notification Delivery Tracking

The original `check_ins` row made offline retries idempotent but did not record
the separate family-notification lifecycle required by AC-15.6/AC-15.10. US-15
adds `check_in_notifications`, one row per check-in with a nominated family
contact. `check_in_id` is unique, so a retry with the same
`client_generated_id` returns the existing check-in and cannot enqueue a second
WhatsApp message. The Meta message ID is also unique and correlates signed
delivery-status webhooks; an accepted message that has not reached `delivered`
by `fallback_due_at` is eligible for exactly one SMS fallback.

This is intentionally **not** a polymorphic notification table shared with
`sos_notifications`. SOS has four independent channels, resolution semantics,
and a future admin retry queue that are not in front of US-15 yet. Generalizing
those requirements now would be speculative US-16 infrastructure. US-16 may
extract common delivery primitives later once its actual channel/retry behavior
is implemented, while this table remains the minimal, check-in-specific record
requested by the current story.

The SMS reference is provider-neutral even though PRD §5.6 resolves the MVP
route to the configured primary OTP provider—Termii today—through a distinct
outbound-message adapter. It does not reuse Termii's OTP endpoint or leak Termii
payloads into the check-in service. The worker passes
`FAMILY_NOTIFY_CHANNEL_PRIMARY` / `FAMILY_NOTIFY_CHANNEL_SECONDARY` into the
delivery service, which rejects a task whose configured role does not match its
channel instead of silently ignoring the deployment policy.

## 6.24 Amendment — US-15 Redis-Outage Notification Ceiling

`CheckInService.create` fails open on the Redis rate limiter (§6.23's review
established this is deliberate: check-in persistence must never be blocked by
infrastructure). Independent review found that failing open had no ceiling of
its own: `check_ins.client_generated_id` uniqueness only rejects an
exact-duplicate retry, not distinct check-ins, so an outage with no other
guard let every rapid, distinct check-in from the same user trigger its own
family WhatsApp/SMS send for as long as Redis stayed down — real notification
cost and, worse, a plausible flood to a family contact's phone. The
client-side 15-minute UI debounce does not close this gap; it only governs
the honest app path and has no effect on a direct API call.

`CheckInService._recent_checkin_already_notified` closes it without touching
the write path: it activates only when the Redis call raised, and queries
`check_ins` for another row from the same user with `received_at` inside the
same 15-minute window the Redis key would have covered. If one exists, this
check-in still gets its own row — the safety-critical write is never
gated — but no `check_in_notifications` row is created for it, so no second
WhatsApp/SMS fires. Once Redis recovers, the existing Redis-backed limiter
governs the very next request as before; this fallback has no effect while
Redis is healthy.

## 6.25 Amendment — US-16 Cancellation and Failed-Channel Auditability

US-16 activates the previously specified `sos_alerts` and
`sos_notifications` tables. The original notification shape represented the
four trigger-time channels, but AC-16.6 also requires a separately deliverable
cancellation follow-up. Reusing and overwriting the trigger rows would erase
whether the original emergency notification was sent. `event` therefore
distinguishes `triggered` from `cancelled`, and the unique key is the explicit
triple `(sos_alert_id, channel, event)`. A retry of one client-generated SOS
still creates only the original four rows; a real cancellation creates exactly
four additional, independently auditable rows.

The admin Failed Notification Queue already present in `api-spec.md` §7.10
also requires state that the original table sketch omitted. `retry_count` and
`admin_queued_at` make the documented three-attempt policy durable across
workers and deployments. A channel failure never changes or rolls back the
underlying `sos_alerts` row. Migration `0016_us16_sos` creates this amended
shape directly because SOS had not been deployed before US-16.

## 6.26 Amendment — US-19 Resolved-Alert Notification Suppression

Independent review of US-16 found that `SOSNotificationService.dispatch()`
and the Celery Beat recovery sweep (`app.sos.enqueue_pending`) never
consulted the parent `sos_alerts.status` before sending or retrying a
`triggered`-event row. A channel that failed once and was still under the
three-attempt cap could therefore still fire minutes after an operator
resolved the alert, violating AC-19.6 ("Resolved SOS sends no further
notifications"). No schema change was needed — both call sites now check
`sos_alerts.status == 'active'` before a `triggered`-event row is sent,
skipping (and logging) rather than erroring if the alert has since moved to
`resolved` or `cancelled`. `cancelled`-event rows are exempt from this
check: `cancel()` always sets the alert to `cancelled` before creating
them, and the state machine never transitions out of `cancelled` again
(§6.25's mutual-exclusion guards), so that half of the notification table
is never at risk of the same race.

This amendment also introduces the browser-push half of AC-19.1, which had
no delivery path at all: `FirebasePushSender.send_topic` already sent real
FCM topic messages, but nothing in the dashboard ever subscribed a browser
to receive them. `FirebasePushSender.subscribe_topic` calls Firebase's
Instance ID API to associate an operator's browser FCM registration token
with `hto-{organization_id}`, the same topic `send_topic` already targets.
No new table is introduced — Firebase's own infrastructure holds the
token-to-topic association; DamDam does not need to persist it to route a
later `send_topic` call correctly.

## 6.27 Amendment — US-22 SOS Family WhatsApp SMS Fallback

AC-22.3 was previously unbuilt: `sos_notification_channel` had no SMS
option at all, so a WhatsApp send that failed or went unconfirmed for the
family contact had no fallback, unlike check-in's already-proven
WhatsApp-to-SMS pattern (§6.23). `sms_family` is added to the channel
enum via `ALTER TYPE ... ADD VALUE`, but — unlike the other four channels,
which are always created together at trigger/cancel time — an
`sms_family` row is created lazily, only if the `whatsapp_family` row
needs the fallback. It is never one of the four rows `SOSService._notifications`
eagerly creates.

Three columns move onto `sos_notifications` rather than a new table,
because the fallback state (was WhatsApp delivered? when is the fallback
due?) belongs to the `whatsapp_family` row it governs, not to a row that
may not exist yet: `whatsapp_message_id` (unique, correlates the Meta
delivery webhook — reused as-is from check-in, since a `wamid` cannot
belong to both a check-in and an SOS notification), `whatsapp_delivered_at`
(distinct from the generic `status`, which stays `sent` once Meta accepts
the message regardless of later delivery — this is what actually
suppresses the fallback), and `fallback_due_at` (the 60-second deadline,
or immediate on an outright send failure rather than a missed
confirmation). These three columns are meaningless for the other three
channels and remain null there.

`SOSNotificationService.send_sms_fallback` reuses the same idempotency
pattern as every other write path in this codebase: it attempts to insert
the `sms_family` row and relies on the `(sos_alert_id, channel, event)`
unique constraint plus an `IntegrityError` catch, not a pre-check select,
so a concurrent retry cannot create two. Once created, the row is
dispatched through the ordinary `dispatch()`/retry/admin-queue machinery
already built for the other four channels — no bespoke `sms_attempt_count`
field was needed the way check-in required one, because SOS's per-channel-
row design already carries `retry_count`/`admin_queued_at` generically.

The Celery Beat sweep for due fallbacks (`app.sos.enqueue_due_fallbacks`,
mirroring check-in's `enqueue_due_fallbacks`) anti-joins against an
existing `sms_family` sibling so it stops re-triggering `send_sms_fallback`
once the fallback row exists at all — that row's own retries, if it failed,
belong to the existing generic recovery sweep (§6.26's
`pending_dispatchable_notifications_query`), not this one.

The SMS sender is the same `TermiiSmsSender` check-in already uses
(`app.notifications.providers`), injected into `SOSProviderAdapter`
alongside the existing WhatsApp/email/push senders — no second SMS vendor
integration was introduced.

## 6.28 Amendment — US-18 Live `sos_status` on the HTO Pilgrim Roster

`GET /hto/pilgrims`'s `sos_status` field (`api-spec.md` §7.8) has existed
since US-10, but was always the schema default `"none"` — no query ever
computed it, even after `sos_alerts` was materialized in US-16.
`HtoPilgrimService.list_pilgrims` now queries `sos_alerts` for the listed
pilgrims' `user_id`s and reports `"active"` if any row is
`SOSStatus.ACTIVE`, `"none"` otherwise. This is a deliberately two-value
signal, matching the existing `esim_status` field's own precedent (see
its comment in `app/esim/schemas.py`): AC-18.4 only needs to distinguish
an unresolved SOS from everything else to drive the risk-sort and
highlight, so a pilgrim's past resolved or cancelled alerts are not
surfaced in this summary — that history remains queryable through
`sos_alerts` directly if a future story needs it. No schema change; this
is a query-only amendment to an already-existing field.

## 6.29 Amendment — US-17 Exposes Purchased Balance Snapshots

The `packages.data_gb_total` and `packages.pstn_minutes_total` columns have
always been immutable snapshots copied from `pricing_tiers` at purchase time
(§6.3). Mid-story review of US-17 found that the package-status API omitted
both fields and returned only the mutable remaining values. That made the
required percentage warning impossible to calculate correctly after reinstall
or whenever the first Home refresh happened after usage had already occurred.

`GET /packages/{id}/status` now returns both existing total fields alongside
their corresponding remaining fields. This is a response-contract correction,
not a schema migration: no stored shape, constraint, or snapshot semantics
change. The numbering deliberately reserves §6.26–§6.28 for concurrent PR #70;
its source changes do not touch the payment package endpoint.
