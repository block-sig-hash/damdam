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

### `caller_id_verifications`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, UNIQUE | One per user |
| twilio_verification_sid | VARCHAR(64) | NOT NULL | |
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
| nahcon_licence_number | VARCHAR(50) | NULLABLE | Required only when `org_type = hto_operator`; must otherwise be null |
| email_verified | BOOLEAN | DEFAULT FALSE | |
| approval_status | ENUM | DEFAULT 'pending' | `pending` \| `approved` \| `rejected` |
| approved_at | TIMESTAMPTZ | NULLABLE | |
| approved_by | UUID | FK → admin_users, NULLABLE | |
| approval_email_sent_at | TIMESTAMPTZ | NULLABLE | Set after the approval email is delivered |
| approval_whatsapp_sent_at | TIMESTAMPTZ | NULLABLE | Set after the approval WhatsApp message is delivered |

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
| manifest_order_id | UUID | FK → manifest_orders, NULLABLE | Set once included in a placed order (§6.5) |
| user_id | UUID | FK → users, NULLABLE | Set once pilgrim activates |
| activation_code | VARCHAR(8) | UNIQUE, NULLABLE | Generated post-payment |
| activation_code_used | BOOLEAN | DEFAULT FALSE | |
| activation_code_expires_at | TIMESTAMPTZ | NULLABLE | 30 days from generation |
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
| invoice_url | VARCHAR(500) | NULLABLE | R2 object URL |
| payment_confirmed_at | TIMESTAMPTZ | NULLABLE | |
| payment_confirmed_by | UUID | FK → admin_users, NULLABLE | Manual confirmation for MVP |

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

---

### `daily_price_cache`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| pricing_tier_id | UUID | FK → pricing_tiers | |
| date | DATE | NOT NULL | |
| ngn_price | DECIMAL(12,2) | NOT NULL | Per-unit (per-person for Family) |
| fx_rate_used | DECIMAL(10,4) | NOT NULL | Audit trail |

**Indexes:** UNIQUE (`pricing_tier_id`, `date`)

---

### `packages`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users | |
| pricing_tier_id | UUID | FK → pricing_tiers | |
| source | ENUM | NOT NULL | `retail` \| `hto_manifest` |
| status | ENUM | DEFAULT 'active' | `active` \| `expired` \| `cancelled` |
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

**Indexes:** `processor_reference` (unique, partial index `WHERE
processor_reference IS NOT NULL`)

---

### `esim_profiles`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| package_id | UUID | FK → packages, UNIQUE | |
| aggregator | ENUM | NOT NULL | `airalo` \| `esim_access` \| `monty` — see §6.6 amendment for why a second/third supplier is a deliberate redundancy decision, not just vendor-shopping |
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

## 6.6 Amendment — Monty Mobile as a Dual eSIM Supplier

**This was decided very early in this project's planning, before
this doc suite existed, and never made it into the committed
spec** — `esim_profiles.aggregator` originally listed only `airalo`
and `esim_access`, missing Monty Mobile entirely despite it having
been identified as the Gulf-specialist redundancy vendor from the
start. Fixed here, following the same amendment pattern as §6.4/§6.5.

**Why a second/third supplier, not just cost-shopping:** the real
justification is redundancy during a concentrated, high-stakes
surge, not marginal price competition. During actual Hajj week,
thousands of pilgrims may attempt eSIM activation within a
compressed window (arrival at Jeddah, a specific prayer time, a
scheduled group movement). If the single eSIM aggregator has a
provisioning outage, an API degradation, or a capacity shortage
during that exact window, there's no fallback — every pilgrim
depending on that provider is affected simultaneously. Monty
Mobile is a credible second supplier specifically because it
operates its own SM-DP+ provisioning infrastructure (not a
reseller sitting on top of someone else's), has genuine Gulf/
Middle East market positioning, and explicitly markets Hajj/Umrah
coverage on its own product pages — this isn't a speculative
addition, it's a provider already oriented toward this exact
market.

**What this does NOT mean:** this is not "pick whichever is
cheapest per request" load-balancing from day one. For MVP, eSIM
Access remains primary (existing integration, per `prd.md` §5.4's
existing dependency list) with Monty onboarded as a qualified,
tested secondary — not dynamically selected per-request until
there's real operational confidence in both providers' reliability
and provisioning latency under load. Dynamic best-price/best-
performance selection by destination is a reasonable Phase 2+
optimization once both integrations are proven, not an MVP
requirement.

**Schema implication beyond the enum change:** no other structural
change is needed — `esim_profiles.aggregator` already existed
specifically to support multiple providers per package, so adding
`monty` as a third value is additive, not a breaking change to
any existing row.

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
