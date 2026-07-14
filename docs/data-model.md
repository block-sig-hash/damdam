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
| verified_cli | BOOLEAN | DEFAULT FALSE | True once Twilio Verify passes |
| departure_date | DATE | NULLABLE | Drives the eSIM banner timing |
| destination_country | VARCHAR(2) | DEFAULT 'SA' | ISO code; hardcoded SA for MVP |
| platform | ENUM | NOT NULL | `ios` \| `android` — set at registration |
| status | ENUM | DEFAULT 'active' | `active` \| `suspended` |
| last_login_at | TIMESTAMPTZ | NULLABLE | |

**Indexes:** `phone_number` (unique), `departure_date`

---

### `emergency_content`

**Design note:** Backs US-12 (scoped down from full offline maps
to just emergency contacts/phrases — see `prd.md` §4.4's scope
note). Keyed by `destination_country` (matching `users.
destination_country`) so a future country expansion is "add a
row," not a code change — same principle as the OTP/eSIM/payment
vendor tables, just for content instead of vendors. Deliberately
minimal: plain text, no images, no map tiles, no file storage —
this is intentionally the cheapest possible version of the
multi-country abstraction, since the feature itself was cut down
to the cheapest possible scope.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| destination_country | VARCHAR(2) | PK | ISO code; `SA` is the only populated row for MVP |
| support_whatsapp_number | VARCHAR(20) | NOT NULL | DamDam's own support number, not destination-specific, but stored per-row for simplicity (avoids a separate global-config lookup) |
| local_emergency_numbers | JSONB | NOT NULL | e.g. `{"police": "999", "ambulance": "997"}` — structure, not free text, so the app can label each number correctly |
| phrasebook | JSONB | NOT NULL | Array of `{phrase_key, translated_text, language_code}` — e.g. `help`, `thank_you`, `where_is`, `i_dont_understand`, `i_need_a_doctor` |
| updated_at | TIMESTAMPTZ | NOT NULL | Content-review timestamp, not a user-facing field |

**Note on the HTO operator's number:** shown alongside this
content on the SOS screen (AC-16.4) but is NOT stored here — it's
pulled live from the pilgrim's actual assigned `organizations` row
(via their manifest/order), since it's specific to each pilgrim's
HTO, not the destination country.

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
| channel | ENUM | NOT NULL | `push` \| `email` \| `whatsapp_operator` \| `whatsapp_family` |
| status | ENUM | DEFAULT 'pending' | `pending` \| `sent` \| `failed` |
| sent_at | TIMESTAMPTZ | NULLABLE | |
| failure_reason | VARCHAR(255) | NULLABLE | |

One row per channel per SOS event — allows the admin failed-
notification queue to retry only the failed channel.

---

### `call_logs`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users | |
| twilio_call_sid | VARCHAR(64) | UNIQUE, NOT NULL | |
| direction | ENUM | NOT NULL | `outbound` only for MVP |
| call_type | ENUM | NOT NULL | `pstn` \| `app_to_app` |
| to_number | VARCHAR(14) | NULLABLE | Null for app-to-app |
| duration_seconds | INTEGER | NOT NULL | |
| pstn_minutes_charged | DECIMAL(6,2) | DEFAULT 0 | 0 for app-to-app |
| started_at | TIMESTAMPTZ | NOT NULL | |
| ended_at | TIMESTAMPTZ | NULLABLE | |

**Indexes:** `user_id`, `twilio_call_sid` (unique)

---

### `device_compatibility_log`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, NULLABLE | |
| platform | ENUM | NOT NULL | `ios` \| `android` |
| device_model | VARCHAR(100) | NOT NULL | |
| os_version | VARCHAR(20) | NULLABLE | |
| esim_supported | BOOLEAN | NOT NULL | |
| checked_at | TIMESTAMPTZ | NOT NULL | |

Feeds the "known incompatible devices" analytics referenced in
the PRD §5.4 — now tracks platform explicitly given dual-platform
scope, since iOS and Android compatibility failures have different
causes (hardware support vs. API absence) and need different
downstream handling.

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
