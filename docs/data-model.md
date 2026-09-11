# Data Model

> **Current scope:** the September 2026 reset in §6.42 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

# DamDam — Version 0.1

Database: PostgreSQL 16. ORM: SQLModel (Pydantic + SQLAlchemy). All
primary keys are UUIDv4 unless noted. All tables have `created_at`
and `updated_at` timestamps (omitted below except where
behaviourally relevant).

---

## 6.1 Entity Overview

```
User (pilgrim)
  ├── has one → VerifiedCallerIdentity   (see §6.40 — supersedes CallerIdVerification)
  ├── has one → FamilyContact
  ├── has many → Package
  ├── has many → EsimProfile (via Package)
  ├── has many → CheckIn
  ├── has many → SosAlert
  ├── has many → CallLog
  ├── has many → CallerIdConsent (via VerifiedCallerIdentity, see §6.40)
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
| verified_cli | BOOLEAN | DEFAULT FALSE | Legacy flag, superseded by `verified_caller_identities.status = active` (§6.40); retained only to drive the one-time login-state migration described there |
| departure_date | DATE | NULLABLE | Drives the eSIM banner timing |
| destination_country | VARCHAR(2) | DEFAULT 'SA' | ISO code; hardcoded SA for MVP |
| locale | ENUM | NOT NULL, DEFAULT 'en' | `en` \| `fr`; explicit reading/notification preference, independent of destination |
| platform | ENUM | NOT NULL | `ios` \| `android` — set at registration |
| status | ENUM | DEFAULT 'active' | `active` \| `suspended` \| `pending_deletion` |
| deletion_requested_at | TIMESTAMPTZ | NULLABLE | Set by `DELETE /me/account`; hard-delete eligibility begins 30 days later |
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

### `caller_id_verifications` — superseded, see §6.40

This table was speced here ahead of US-14's implementation and was
never migrated or built — the shipped code took a shortcut instead
(`users.verified_cli` set directly from the account-setup login OTP,
with no separate verification row at all). §6.40 replaces this
design with `verified_caller_identities`, which fixes the shortcut
this table's own absence enabled: CLI verification decoupled from
login OTP entirely, not just provider-agnostic within it.

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
| locale | ENUM | NOT NULL, DEFAULT 'en' | Recipient's own `en` \| `fr` notification preference |

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
| locale | ENUM | NOT NULL, DEFAULT 'en' | Operator dashboard and notification preference |
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
| locale | ENUM | NOT NULL, DEFAULT 'en' | Optional CSV `locale`; otherwise copied from the organization at upload |
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
| processor | ENUM | NULLABLE | `paystack` \| `flutterwave`; NULL only for a processor-neutral manually confirmed HTO invoice — see §6.39 |
| processor_reference | VARCHAR(100) | UNIQUE, NULLABLE | Idempotency key (Path A); replaces the earlier Paystack-only `paystack_reference` field |
| amount_ngn | DECIMAL(12,2) | NOT NULL | |
| payment_method | ENUM | NULLABLE | `card` \| `bank_transfer` \| `ussd` \| `invoice` |
| status | ENUM | NOT NULL | `pending` \| `success` \| `failed` |
| webhook_payload | JSONB | NULLABLE | Minimized provider reconciliation evidence, or minimal manual-confirmation evidence; never a raw provider body — see §6.39 and `security.md` §10.13 |
| receipt_sent_at | TIMESTAMPTZ | NULLABLE | Set after all applicable receipt channels succeed; permits safe retry after a notification outage |
| created_at | TIMESTAMPTZ | NOT NULL | Starts the 6-year retention window in `security.md` §10.3 |

**Indexes:** `processor_reference` (unique, partial index `WHERE
processor_reference IS NOT NULL`), `manifest_order_id` (unique; multiple NULLs
permitted), `created_at`

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
| esim_profile_id | UUID | NOT NULL | Pseudonymous source identifier; deliberately not an FK so account erasure cannot cascade-delete retained usage |
| polled_at | TIMESTAMPTZ | NOT NULL | |
| data_used_gb | DECIMAL(6,2) | NOT NULL | Cumulative, from aggregator |
| poll_success | BOOLEAN | NOT NULL | |

**Indexes:** `esim_profile_id`, `polled_at` — subject to the 30-day
raw / daily-summary retention policy, see security.md §10.3

### `daily_usage_summaries`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| esim_profile_id | UUID | NOT NULL | Pseudonymous source identifier; deliberately not an FK so account erasure cannot cascade-delete the aggregate |
| summary_date | DATE | NOT NULL | UTC calendar date |
| first_polled_at | TIMESTAMPTZ | NOT NULL | Timestamp of the first represented reading |
| last_polled_at | TIMESTAMPTZ | NOT NULL | Timestamp of the last represented reading |
| first_data_used_gb | DECIMAL(6,2) | NOT NULL | Earliest cumulative reading that day |
| last_data_used_gb | DECIMAL(6,2) | NOT NULL | Latest cumulative reading that day |
| successful_poll_count | INTEGER | NOT NULL | Successful raw polls represented |
| failed_poll_count | INTEGER | NOT NULL | Failed raw polls represented |

**Unique constraint:** (`esim_profile_id`, `summary_date`). Raw polls older
than 30 days are merged into this row before deletion, preserving daily usage
movement and reliability analytics without row-level timing granularity.

---

### `check_ins`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, NULLABLE, ON DELETE SET NULL | Identity link removed on account erasure; aggregate row retained |
| client_generated_id | UUID | UNIQUE, NOT NULL | Set on-device; offline-retry idempotency key |
| timestamp | TIMESTAMPTZ | NOT NULL | Client-side event time |
| latitude | DECIMAL(9,6) | NULLABLE | |
| longitude | DECIMAL(9,6) | NULLABLE | |
| received_at | TIMESTAMPTZ | NOT NULL | Server receipt time |
| location_retention_due_at | TIMESTAMPTZ | NOT NULL | Later of the event time or latest known package expiry, plus 90 days; drives location nulling without a heuristic join |

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
| user_id | UUID | FK → users, NULLABLE, ON DELETE SET NULL | Identity link removed on account erasure; alert remains until its 3-year mark |
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
| user_id | UUID | FK → users, NULLABLE, ON DELETE SET NULL | Identity link removed on account erasure; log remains until its 12-month mark |
| telnyx_call_leg_id | VARCHAR(64) | UNIQUE, NOT NULL | Stable Telnyx call-leg correlation ID; `call_control_id` remains the command token and is not persisted as identity |
| direction | ENUM | NOT NULL | `outbound` only for MVP |
| call_type | ENUM | NOT NULL | `pstn` \| `app_to_app` |
| to_number | VARCHAR(14) | NULLABLE | Recipient Nigerian number for PSTN and app-to-app history; nullable only when a provider event lacks a resolvable destination |
| duration_seconds | INTEGER | NOT NULL | |
| pstn_minutes_charged | DECIMAL(6,2) | DEFAULT 0 | 0 for app-to-app |
| started_at | TIMESTAMPTZ | NOT NULL | |
| ended_at | TIMESTAMPTZ | NULLABLE | |
| verified_caller_identity_id | UUID | FK → verified_caller_identities, NULLABLE, ON DELETE SET NULL | NULL for `app_to_app`; added by §6.40, the CLI actually used for a `pstn` leg |
| idempotency_key | VARCHAR(64) | NULLABLE | Added by §6.40; client-generated key from the call-initiation request, distinct from `telnyx_call_leg_id` which only exists once Telnyx accepts the leg |
| requested_provider | ENUM | NULLABLE | Added by §6.40; `telnyx` \| `idt` — which configured provider the backend selected, independent of `idt_calling_enabled` ever being true in this MVP |
| failure_code | VARCHAR(64) | NULLABLE | Added by §6.40; provider or internal rejection reason (e.g. `cli_policy_rejected`, `insufficient_balance`) |
| failure_description | VARCHAR(255) | NULLABLE | Added by §6.40; safe, user-facing text — never a raw provider error body |

**Indexes:** `user_id`, `telnyx_call_leg_id` (unique), `verified_caller_identity_id`, `idempotency_key`

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
| locale | ENUM | NOT NULL, DEFAULT 'en' | Persisted admin dashboard preference |

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

## 6.30 Amendment — US-25 AC-25.3 Package Validity and Chaining

AC-25.3 ("one active package per destination per trip period") turned out
not to mean "block a second purchase" once checked against a real product
scenario: a pilgrim who exhausts a package's data/voice mid-trip and rebuys
should get immediate use of the new tier's allowance, and a pilgrim with two
genuinely separate future trips (e.g. Umrah now, Hajj next year) must not be
blocked either. Blocking the second, genuinely-paid purchase also has no
good answer for what happens to the money already collected — no refund
infrastructure exists in this codebase today (confirmed: no refund method
exists on any payment provider abstraction, and `api-spec.md` §7.13 already
treats refund processing as out of scope for the MVP admin UI, a direct
database action instead). Chaining avoids that problem entirely by never
creating a stranded, paid-for, blocked package in the first place.

**`pricing_tiers.validity_days`** (`int`, `NOT NULL`, `server_default '30'`)
is new: how many days a package provisioned from that tier remains valid,
governing both a fresh package's `expires_at` and how a chained renewal's
new window is computed. Intended real values are 7/15/30 days for the
base/medium/high retail tiers, admin-configured the same way `ngn_price`
already is (§6.16) — there is no seed or tier-creation endpoint in this
codebase at all yet, so setting real values remains a direct database
action until one exists, same MVP-scope precedent as §6.16.

**`PackageStatus.SUPERSEDED`** is a new terminal status, added via
`ALTER TYPE package_status ADD VALUE`, distinct from `EXPIRED`: `EXPIRED`
means a package ran out of its own validity window unrenewed; `SUPERSEDED`
means a later purchase chained onto it and replaced it before that
happened.

**Chaining mechanics** (`app/packages/service.py`,
`PackageChainingService.chain()`), invoked from both provisioning paths
(the payment webhook success handler and activation-code redemption,
replacing what those two paths used to do — populate a package's balance
and `expires_at` directly from the tier alone):

- If the purchasing user has no package with `status = 'active'`, the new
  package gets a fresh window: `expires_at = now + validity_days`, no
  balance carried in.
- If an active package exists and its `expires_at` is still in the future,
  the purchase is a genuine rebuy: the new package's window starts from
  the *current* package's `expires_at` (not from the purchase moment,
  which is what makes this a renewal rather than two overlapping
  purchases), its unused `data_gb_remaining`/`pstn_minutes_remaining` roll
  forward on top of the new tier's own allowance, and the current package
  flips to `SUPERSEDED`.
- If an active package exists but its `expires_at` has already passed,
  it represents a concluded, unrenewed past trip, not a rebuy — nothing
  in this codebase currently sweeps packages to `EXPIRED` on a schedule,
  so a package can sit at `status = 'active'` past its own window
  indefinitely. Chaining lazily corrects this: the stale package is
  flipped to `EXPIRED` (not `SUPERSEDED`) when discovered, its balance is
  *not* rolled forward, and the new package gets a fresh window from now.
  This keeps "exactly one `ACTIVE` package per user" true as an invariant
  without requiring new background sweep infrastructure — every other
  reader of "the active package" in this codebase (e.g. the PSTN balance
  lookup in `app/voice/service.py`) continues to work unmodified.
- The boundary (`expires_at == now`, exactly) is treated as already
  expired, not still valid.

**Top-ups** (a separate voice/data top-up purchase, distinct from a
full-package rebuy) inherit the parent package's existing validity window
rather than carrying an independent one of their own — the same chaining
mechanics apply, with the top-up's own tier's `data_gb`/`pstn_minutes`
rolling into `extra_data_gb`/`extra_pstn_minutes` the same way a rebuy's
leftover balance does, rather than opening a second concurrent window.
Note: no top-up purchase flow exists yet in this codebase (retail purchase
and activation redemption both provision full packages only) — this
documents the intended mechanics for when one is built, not a currently
reachable code path.

**Admin reversal** — a pilgrim who mistakenly buys twice needs a way for
an admin to undo one purchase. In scope for US-25: a minimal
`POST /admin/packages/{id}/cancel` (see `api-spec.md`) that sets the
target package's `status` to `CANCELLED` and writes an audit log entry
(§6.31, `PACKAGE_CANCELLED_BY_ADMIN`) — cancel-only, no automatic balance
reversal, chain re-linking, or payment refund/credit. This mirrors the
same MVP-scope precedent as `validity_days` above: `api-spec.md` §7.13
already treats refund processing and manual package editing as direct
database actions for MVP, not admin-UI features. A smarter automatic
reversal (unwinding a chain, crediting/refunding the superseded
transaction) is explicitly future work, tied to the payment-abstraction
refund capability `scaling-infrastructure.md` already lists as a
post-MVP goal — no such infrastructure exists today.

## 6.31 Amendment — US-25 AC-25.4 `audit_log` Table

No audit trail existed anywhere in this schema before US-25: duplicate
payment-webhook retries (AC-25.1) and duplicate activation-code redemption
attempts (AC-25.2) were already correctly absorbed as silent no-ops, but
left no record for admin review, and the new AC-25.3 chaining decision
(§6.30) needed the same treatment. A single minimal table covers all three,
plus the admin-cancel action above:

```
audit_log
  id              UUID PK
  created_at      TIMESTAMPTZ NOT NULL, indexed
  event_type      VARCHAR(64) NOT NULL, indexed
  user_id         UUID NULL, FK -> users.id ON DELETE SET NULL, indexed
  reference       VARCHAR(255) NULL
  outcome         VARCHAR(64) NOT NULL, indexed
  details         VARCHAR(500) NULL
  idempotency_key VARCHAR(255) NULL, unique, indexed
```

`event_type` and `outcome` are deliberately plain `VARCHAR`, not
Postgres-native enum types — this table is meant to absorb new event
sources and outcomes over time without a migration each time; type safety
for the values actually written is enforced in application code via the
`AuditEventType`/`AuditOutcome` Python enums (`app/audit/models.py`), not
the database schema. `user_id` is `ON DELETE SET NULL` rather than
`CASCADE`, unlike most user-owned tables in this schema, so the audit trail
survives account deletion instead of disappearing with it. `reference` is
deliberately untyped/unvalidated — a payment `processor_reference`, an
activation code, or a package id, whichever is relevant to the event — this
is a log, not a foreign key to any one of those tables.
`idempotency_key` is optional for existing US-25 writers; retention tasks set
it deterministically from the action and target row so rerunning a sweep cannot
create a second audit record for the same mutation.

Current write sites (`app/audit/service.py`, `AuditLogService.record()`,
which never commits on its own — each caller commits it as part of its own
transaction, since in both duplicate-detection paths the audit write must
survive an exception that's about to unwind the rest of the transaction):

- `duplicate_webhook_absorbed` — a payment webhook retry that resolves to
  an already-processed transaction (`app/payments/service.py`).
- `duplicate_activation_attempted` — a second redemption attempt on an
  already-used activation code, from either of the two places
  `ActivationError("activation_code_already_used")` can be raised
  (`app/activation/service.py`).
- `package_chained_onto_active_window` — §6.30's chaining path actually
  superseded an existing active package, from both provisioning paths.
- `package_cancelled_by_admin` — the admin-cancel endpoint (§6.30).

No admin UI to browse this log is in scope for US-25 — only the table and
the write-path, per the same reasoning as the cancel endpoint's own scope
above.

## 6.32 Amendment — `packages.destination_country` (Multi-Destination Audit)

`users.destination_country` (§2, `VARCHAR(2) DEFAULT 'SA'`) has always been
the only place this codebase records a pilgrim's destination — a single,
account-level value, hardcoded to `'SA'` for MVP with no flow that ever
sets it to anything else. An audit ahead of any real second-destination
product decision found that this shape had already produced a real latent
bug: §6.30's AC-25.3 chaining/superseding query
(`PackageChainingService.chain()`, `app/packages/service.py`) and voice's
active-package PSTN balance lookup (`app/voice/service.py`,
`_remaining_balance` and the hangup-billing query) both picked "the
active package for this `user_id`" with no destination dimension at all —
correct only because exactly one destination has ever existed. Once a
second destination is real, both would misbehave: chaining would
incorrectly supersede or roll balance from an unrelated destination's
package into a brand-new one, and voice would silently bill minutes
against whichever package happened to be purchased most recently,
regardless of which destination the call was actually relevant to.

**`packages.destination_country`** (`VARCHAR(2) NOT NULL DEFAULT 'SA'`,
migration `0019_pkg_destination_country`) closes this: an immutable
purchase-time snapshot of the purchasing user's `users.destination_country`
at the moment the package is created, the same pattern as the existing
`data_gb_total`/`pstn_minutes_total` snapshots (§6.29) — not a live
reference to the user's current value, so a user's destination changing
later (whenever a real flow for that exists) never rewrites the
destination of packages already bought. Set at both provisioning paths
(`app/payments/service.py` `initialize()`/`process_webhook()`,
`app/activation/service.py` `redeem()`), read from the `User` row already
in scope at each site. Existing rows are backfilled via the migration's
`server_default` — every package that has ever existed was purchased by a
user whose `destination_country` has only ever been `'SA'`, so this is the
historically correct value, not just a convenient default; verified
against a real Postgres database with pre-existing rows inserted before
the migration ran, not just a fresh empty schema.

**The invariant this changes:** §6.30 states chaining keeps "exactly one
`ACTIVE` package per user" true. That is no longer correct on its own —
the actual invariant, as of this amendment, is "exactly one `ACTIVE`
package per `(user, destination)`." `PackageChainingService.chain()` now
takes a `destination_country` parameter and filters/supersedes only
within that destination; a purchase for a new destination never touches,
chains onto, or rolls balance from another destination's active package.
Voice's two active-package lookups now filter by
`Package.destination_country == user.destination_country` — reusing the
same field the chaining fix threads through, not a new signal — so a call
bills against the package matching the destination the user's account
currently indicates, not whichever package is newest.

**Explicitly out of scope for this amendment** (found during the same
audit, deliberately not built here — each requires a real product
decision this task doesn't make): US-13's 150km Jeddah geofence trigger
is hardcoded as native Android constants
(`apps/mobile/android/.../ArrivalPromptModule.kt`) with no config layer at
all; `pricing_tiers` has no destination dimension and the eSIM vendor
cascade (`app/esim/providers.py`) hardcodes `"destination_country": "SA"`
in the outbound vendor payload for both `HttpEsimProvider`-based vendors,
with `EsimIssueRequest` carrying no destination field for any provider to
honor even if that were fixed. US-12's bundled Arabic emergency phrasebook
(`apps/mobile/src/content/emergencyEssentials.ts`) was already correctly
identified in §6.20 as an intentional MVP-scoped decision with its own
documented multi-country trigger condition, and needs no change here.

## 6.33 Amendment — Package Destination/Status Lookup Index

`packages` now has the composite non-unique index
`ix_packages_user_destination_status` over
`(user_id, destination_country, status)`. This is the exact equality-filter
prefix used by `PackageChainingService.chain()`'s locked active-package lookup
and both voice-billing active-package lookups (`_remaining_balance` and hangup
billing). The index closes the performance half of §6.32: those queries became
destination-correct there, but would otherwise scan a user's package history
as the table grows. It does not add a uniqueness constraint; concurrency and
the one-active-package-per-(user,destination) lifecycle invariant remain
service/transaction concerns.

No destination catalogue or second product destination is introduced. Synthetic
KE rows are used only in query-plan verification to prove selectivity across the
destination column.

## 6.34 Amendment — US-13 `destination_geofences`

US-13's Android arrival trigger is now backed by a destination-keyed table:

```
destination_geofences
  destination_country  VARCHAR(2) PK
  latitude             DOUBLE PRECISION NOT NULL
  longitude            DOUBLE PRECISION NOT NULL
  radius_meters         DOUBLE PRECISION NOT NULL
```

The migration inserts exactly one real row: `SA` → Jeddah (`21.4858`,
`39.1925`, `150000`). `GET /packages/{id}/geofence` ownership-checks the
package, then resolves this row from the package's immutable
`destination_country` snapshot (§6.32). Missing destinations return a clear
404 and never fall back to SA; the Android native bridge is parameterized with
the returned coordinates, radius, and request ID rather than compiling Jeddah
into the registration method.

Still out of scope: a second destination's coordinates, destination-specific
arrival copy, and an iOS native geofencing implementation. AC-13.7's date banner
is unchanged.

## 6.35 Amendment — `pricing_tiers.destination_country`

`pricing_tiers.destination_country` (`VARCHAR(2) NOT NULL DEFAULT 'SA'`) adds
the missing destination dimension to mutable catalogue pricing. The migration
uses the same PostgreSQL fast-default/backfill pattern as
`packages.destination_country` (§6.32); because SA is the only destination ever
sold, SA is the historically correct value for every pre-existing tier.

Retail and manifest/admin pricing service reads accept an optional destination
filter and preserve their existing all-active-tiers behavior when it is absent.
The public unauthenticated `GET /pricing/tiers` intentionally supplies no
filter: there is no trustworthy anonymous destination signal or approved
destination-selection UX yet. Purchase paths still bind an explicit
`pricing_tier_id`; group-tier resolution remains destination-unaware until a
real second destination creates product requirements and data for resolving
otherwise ambiguous active group tiers.

No KE or other second-destination tier is seeded; synthetic rows exist only in
tests proving that the query filter discriminates by destination.

## 6.36 Amendment — Destination-Aware eSIM Vendor Configuration

The internal `EsimIssueRequest` vendor-abstraction contract now carries
`destination_country`, sourced from the immutable package snapshot (§6.32).
`HttpEsimProvider` forwards that value instead of a literal SA vendor payload.
eSIM Access package-code configuration is now a JSON string map keyed as
`"COUNTRY:GB"` (for example `{"SA:5": "SA_5GB"}`), replacing the prior
data-only integer key. String composite keys deliberately preserve native
`pydantic-settings` JSON environment parsing.

Deployment must update the production `ESIM_ACCESS_PACKAGE_CODES` value
atomically with this code; legacy GB-only keys intentionally do not match the
new destination-aware lookup and would make eSIM Access report every tier as
unconfigured before the cascade tries the next provider.

Only existing SA vendor codes may be configured. A missing
`(destination_country, data_gb)` combination raises the existing clear
`EsimProviderError` and may proceed through the configured provider cascade; it
never reuses an SA code for another destination. No second destination, package
code, or provider-specific product data is invented here.

§6.20 remains correct without change: US-12 explicitly requires the Arabic
emergency essentials to be bundled offline, and already names onboarding a real
second destination as the trigger for revisiting country-keyed content. That
trigger has not occurred, so `apps/mobile/src/content/emergencyEssentials.ts`
is intentionally untouched.

---

## 6.37 Amendment — Automated Data Retention State and Audit Idempotency

The retention schedule in `security.md` §10.3 is now materialized by independent
scheduled tasks. The schema gains only the state those tasks require:

- `users.status` adds `pending_deletion`, and `users.deletion_requested_at`
  records the start of the 30-day grace period initiated by
  `DELETE /me/account`.
- `usage_polls`, previously specified but not migrated, is materialized along
  with `daily_usage_summaries`. The summary records the first and last
  cumulative usage reading plus successful/failed poll counts for each UTC day.
  Their `esim_profile_id` is retained as a pseudonymous source identifier but
  deliberately has no foreign key, so deleting account-owned package/eSIM rows
  cannot prematurely remove raw or summarized analytics.
- `check_ins.location_retention_due_at` is persisted when the check-in is
  accepted as the later of its event time or the latest known package expiry,
  plus 90 days. Existing rows are backfilled the same way. This avoids relying
  on a package-window timestamp join that offline delivery or client clock skew
  could fail to match forever.
- `transactions.created_at` supplies the start of the six-year financial
  retention window for both existing and future records.
- `audit_log.idempotency_key` is nullable and unique. Retention actions use a
  deterministic action-and-row key, preventing duplicate audit entries if a
  sweep is retried while leaving all pre-existing US-25 audit behavior
  unchanged.

All retention sweeps share a PostgreSQL transaction-level advisory lock. The
jobs remain distinct and independently callable, but overlapping Beat/manual
runs cannot split an aggregation group, race a cascade, or duplicate a
destructive action.

Account erasure must not silently shorten separately mandated retention.
Accordingly, `check_ins.user_id`, `sos_alerts.user_id`, and `call_logs.user_id`
become nullable with `ON DELETE SET NULL`: account hard deletion removes their
identity link, while their own 90-day-location, three-year, and 12-month tasks
continue to govern the retained rows. `transactions` already survive package
deletion through their nullable `package_id`; the new six-year task is their
only age-based deletion path. `device_compatibility_log` already uses the same
nullable `ON DELETE SET NULL` relationship required by its 90-day PII-strip
rule.

---

## 6.38 Amendment — HTO Pilgrim Summary Manifest Label

No column or table change — this is a response-shape addition over existing
data. `HtoPilgrimService.list_pilgrims` (`apps/api/app/esim/service.py`)
already joined `manifest_pilgrims` to `manifests` and already aggregated
across every manifest an organization owns when called with no `manifest_id`
filter; the API response (`HtoPilgrimSummary`, `apps/api/app/esim/
schemas.py`) simply never surfaced which manifest each row came from, since
the only caller (`/manifests/[id]`, frontend-dashboard.md §9.3 Screen 4) had
the manifest implied by the URL and never needed it.

The cross-manifest HTO Home roster (frontend-dashboard.md §9.7 amendment)
does need it — a table aggregating pilgrims from several manifests has no
other way to label which manifest a given row belongs to. `HtoPilgrimSummary`
gains `manifest_id: UUID` (always present — every `manifest_pilgrims` row has
a non-null `manifest_id`) and `manifest_name: str | None` (nullable, matching
`manifests.name`'s own nullability). See api-spec.md §7.8.

---

## 6.39 Amendment — Minimized Webhook Evidence and Manual HTO Transactions

Migration `0024_retention_payment_gaps` closes two gaps in the six-year
financial record lifecycle.

`transactions.webhook_payload` is no longer a raw provider-body archive. New
Paystack and Flutterwave callbacks are reduced after signature verification to
the explicit reconciliation allowlists in `security.md` §10.13, and the
migration rewrites existing JSONB values to those same shapes. The column name
is retained to avoid an unnecessary schema rename, but its contract is now
"minimized payment evidence." Customer and payment-instrument identifiers are
not hashed because the retained processor references already support
reconciliation without creating a second long-lived linkage identifier.

Manual HTO invoice confirmation creates one successful transaction with:

- `manifest_order_id` set to the confirmed order and protected by a unique
  index;
- `processor = NULL`, because neither Paystack nor Flutterwave processed the
  bank-transfer invoice;
- an internal, globally unique `processor_reference` of `hto-{order_id}`;
- `payment_method = invoice`, the order's `total_ngn`, and a minimal evidence
  object containing confirmation source, admin ID, and timestamp; and
- `created_at` equal to the payment confirmation time, which starts the same
  six-year retention clock used for automated payments.

The existing `processor` server default is removed. Retail payment code already
sets an explicit Paystack or Flutterwave processor, while the database check
permits a NULL processor only for an invoice transaction whose internal
reference starts with `hto-` (the reference remains after an order FK is later
set NULL). The migration backfills one equivalent transaction for every
previously confirmed HTO order without one before creating the unique index.
Confirmation locks the order, writes its state and transaction atomically, and
heals a missing transaction when an already-confirmed order is retried;
provisioning dispatch remains a separate, safely retryable post-commit step.

---

## 6.40 Amendment — Verified Caller Identity (US-14 CLI Hardening)

Replaces the never-implemented `caller_id_verifications` design (§6's
original, now superseded) with a CLI authorization model decoupled
from account login OTP entirely. See `docs/verified-cli-scoping.md`
for the full gap analysis and the founder/product decisions this
amendment defers rather than assumes (NIN identity verification,
IDT Express timing).

### `verified_caller_identities`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, NOT NULL | One active row per user for MVP — see uniqueness note below |
| phone_number | VARCHAR(14) | NOT NULL | E.164; independent of `users.phone_number` — AC-14.10 |
| detected_country | VARCHAR(2) | NOT NULL | ISO code from normalization; `NG` only accepted for MVP |
| detected_carrier | VARCHAR(32) | NULLABLE | Reserved for a future carrier-lookup vendor integration — deliberately deferred, not stubbed, in this MVP pass (`docs/verified-cli-scoping.md` §5); no vendor is chosen yet, so this column is always `NULL` for now and must never be inferred from number prefix alone, since numbers port between carriers |
| phone_verification_provider | ENUM | NOT NULL | `telnyx` for MVP; kept as an enum, not hardcoded, matching the OTP/payment/eSIM provider-abstraction pattern used throughout this doc |
| phone_verification_reference | VARCHAR(64) | NULLABLE | Telnyx Verified Numbers reference; opaque, not the verification code itself |
| phone_verification_status | ENUM | NOT NULL, DEFAULT `not_started` | `not_started` \| `pending` \| `verified` \| `failed` \| `expired` |
| phone_verified_at | TIMESTAMPTZ | NULLABLE | |
| identity_provider | ENUM | NULLABLE | `mock` for MVP (`NIN_VERIFICATION_ENABLED=false`); real providers added only once the founder/legal review in `docs/verified-cli-scoping.md` §4 resolves |
| identity_verification_reference | VARCHAR(64) | NULLABLE | Provider reference, never a raw identity document number |
| identity_verification_status | ENUM | NOT NULL, DEFAULT `not_required` | `not_required` \| `pending` \| `approved` \| `rejected` — `not_required` is the MVP default while identity verification stays disabled |
| nin_msisdn_match_status | ENUM | NOT NULL, DEFAULT `not_checked` | `not_checked` \| `matched` \| `not_matched` \| `unavailable` — must never be set to `matched` unless a provider explicitly returned that match; defaults toward `unavailable`, not a silent pass |
| status | ENUM | NOT NULL, DEFAULT `unverified` | State machine below |
| consent_version | VARCHAR(20) | NULLABLE | Set on activation; matches the version in the linked `caller_id_consents` row |
| consent_at | TIMESTAMPTZ | NULLABLE | Denormalized from `caller_id_consents` for fast activation checks |
| expires_at | TIMESTAMPTZ | NULLABLE | Reverification interval, configurable; NULL means no forced expiry in MVP |
| last_reverified_at | TIMESTAMPTZ | NULLABLE | |
| risk_status | ENUM | NOT NULL, DEFAULT `normal` | `normal` \| `elevated` \| `blocked` — fraud-control input, not a replacement for `status` |
| suspension_reason | VARCHAR(255) | NULLABLE | Set on `suspended`/`revoked`; safe, user-facing text |
| created_at | TIMESTAMPTZ | NOT NULL | |
| updated_at | TIMESTAMPTZ | NOT NULL | |

**State machine:** `unverified` → `phone_verification_pending` →
`phone_verified` → (`identity_verification_pending` →
`identity_verified`, skipped entirely while
`NIN_VERIFICATION_ENABLED=false`, in which case `phone_verified`
goes directly to `consent_required`) → `consent_required` →
`active`. `active` may transition to `suspended` (reversible, e.g.
risk hold), `expired` (reversible via reverification), or `revoked`
(terminal — a fresh `verified_caller_identities` row is required to
re-authorize the same number). Only service-layer transition
methods may change `status`; no route or admin action writes this
column directly, matching the existing `manifest_orders.status`
pattern (`data-model.md` §6.5) of explicit, auditable transitions
rather than arbitrary updates.

**Confirm-attempt lockout:** `phone_verification_pending` → `confirm` is
guarded by its own Redis-backed attempt lockout
(`CallerIdentityService._enforce_confirm_lock`), keyed by `identity_id` and
distinct from `start_verification`'s per-user rate limit. Without this, the
SMS code could be brute-forced against a single already-issued
`phone_verification_reference` with no limit on guesses, defeating the
phone-possession proof this table exists to establish. After
`cli_verification_confirm_attempt_limit` wrong codes (default 3), further
confirm attempts against that `identity_id` are rejected
(`cli_verification_rate_limited`) for `cli_verification_confirm_lockout_seconds`
(default 60s) — the same shape as `OTPService`'s `otp_attempt_limit`/
`otp_lockout_seconds`. This state lives in Redis, not a DB column, matching
where the analogous OTP challenge/attempt state already lives.

A CLI is usable for an outbound `pstn` call only when `status =
active`. `users.verified_cli` is retained (see the table note where
it's defined) purely to drive a one-time migration: existing rows
with `verified_cli = true` get a `verified_caller_identities` row
created at `phone_verified` (not `active`) using `users.phone_number`
as a starting point, since the account already proved possession of
that specific number through the (soon-superseded) login-OTP
shortcut — but `active` still requires a fresh consent capture,
because consent was never actually collected under that shortcut.

**Uniqueness:** `user_id` is NOT unique alone — a user may have
multiple non-`active` rows across verification attempts (e.g. a
failed attempt followed by a retry with a different number), but a
partial unique index enforces at most one `active` row per user:

```sql
CREATE UNIQUE INDEX ux_verified_caller_identities_active_user
  ON verified_caller_identities (user_id)
  WHERE status = 'active';
```

A second partial unique index prevents the same Nigerian number
from being `active` on two unrelated accounts at once (SIM-swap and
number-recycling risk):

```sql
CREATE UNIQUE INDEX ux_verified_caller_identities_active_number
  ON verified_caller_identities (phone_number)
  WHERE status = 'active';
```

**Indexes:** `user_id`, `phone_number`, the two partial unique
indexes above.

### `caller_id_consents`

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| user_id | UUID | FK → users, NOT NULL | Denormalized from the identity row for direct audit queries |
| verified_caller_identity_id | UUID | FK → verified_caller_identities, NOT NULL | |
| consent_version | VARCHAR(20) | NOT NULL | References the exact consent copy shown, matching the `prd.md` §5.5 consent text pattern |
| consented_at | TIMESTAMPTZ | NOT NULL | |
| ip_address | VARCHAR(45) | NULLABLE | IPv4/IPv6; audit context, not used for access control |
| device_session_id | VARCHAR(64) | NULLABLE | Correlates to the existing session/device tracking used elsewhere (`refresh_tokens`, `device_tokens`) rather than inventing a new identifier scheme |
| revoked_at | TIMESTAMPTZ | NULLABLE | Set by explicit revocation, lost-SIM report, or admin suspension; immediately blocks new calls per AC-14.11 regardless of `verified_caller_identities.status` |
| revocation_reason | VARCHAR(255) | NULLABLE | `user_revoked` \| `lost_sim` \| `admin_suspended` \| `admin_fraud_hold`, free text allowed for admin actions |

**Indexes:** `verified_caller_identity_id`, `user_id`

### `call_logs` additive columns

See the updated `call_logs` table above (§6 base schema) —
`verified_caller_identity_id`, `idempotency_key`,
`requested_provider`, `failure_code`, `failure_description` are
added by this amendment's migration rather than a new parallel call-
record table, since `call_logs` already carries the correlation ID,
duration, and billing fields a second table would only duplicate.

### Why not a wallet/ledger table

The proposal this amendment responds to assumed money-denominated
wallet billing with temporary reservations. DamDam's actual billing
for voice is minutes decremented from a `destination_country`-scoped
`packages.pstn_minutes_remaining` (§5.7, `_handle_hangup`'s row-locked
read-then-charge). This amendment does not introduce a parallel
billing model; CLI verification is orthogonal to how a call, once
authorized, gets charged.

---

## 6.41 Amendment — English/French Recipient Locale

Migration `0026_i18n_locales` creates the shared `locale` enum (`en`, `fr`) and
adds a non-null, English-defaulted preference to `users`, `organizations`,
`admin_users`, `family_contacts`, and `manifest_pilgrims`. Existing records are
backfilled to English.

Locale is an account or message-recipient preference and is deliberately
independent of `destination_country`. Signup and OTP recovery persist the
mobile selection on `users`; HTO registration persists the browser selection
on `organizations`. Family-contact nomination accepts the contact's own locale.
Manifest CSVs may include an optional `locale` column; when absent, each staged
pilgrim snapshots the owning organization's locale so activation messages sent
before account creation have a deterministic language.

Auth and HTO login responses expose the persisted locale so mobile secure
session state and dashboard locale cookies can restore an explicit choice
before device/browser inference. Only `en` and `fr` are valid in this release;
BCP 47 regional variants resolve to their base language at the client boundary.

---

## 6.42 Amendment — Product Reset Supersedes the Hajj Schema Scope

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — no table, column, constraint or migration changes here.

`prd.md` §10 resets the product to generic global consumer plus
enterprise/government connectivity. That changes what this schema must describe,
but **nothing above is deleted**: amendments §6.1–§6.41 remain the record of
what was designed and shipped, and the tables they define still exist in
deployed databases.

Read every section above against
[`implementation/SCOPE-DISPOSITION.md`](./implementation/SCOPE-DISPOSITION.md),
which classifies each legacy concept as retired, generalized, deferred or
historical. In particular:

- `family_contacts`, `sos_alerts`, `sos_notifications` and
  `destination_geofences` describe features scheduled for retirement. The
  `check_ins` and `check_in_notifications` disposition remains a proposed
  product default in `implementation/DECISIONS.md`.
  Chunk 04 owns their removal, following the migration sequence in
  `implementation/IMPLEMENTATION-PLAN.md` §7 Phase 1 — stop enrollment and
  dispatch, drain queued work, delete per the retention policy, and drop schema
  only after compatibility requirements end. Order, payment and audit history is
  never erased because a screen was removed.
- `caller_id_verifications` (already superseded by §6.40) and `verified_cli`
  describe **deferred** scope. The launch outbound identity is the
  carrier-assigned number.
- `voice_credentials` describes the **retired** app/WebRTC calling mechanism.
  Carrier line and number lifecycle replaces it in chunk 15.
- `organizations`, `manifests`, `manifest_pilgrims` and `manifest_orders` are
  **generalized** into organizations, memberships, people imports and bulk
  allocations by chunks 07, 22 and 23.
- NGN-only money and the `pricing_tiers` model are **generalized** into
  multi-currency amounts with tariff versions by chunks 05, 09 and 10.

The contracts the reset schema must satisfy are registered as `US-28`, `US-32`
and `US-35` in `prd.md` §10.5. Chunk 05 introduces them as numbered amendments
from §6.43 onward, additive first, preserving historical receipts, balances,
orders and audit history through every upgrade.

## 6.43 Amendment — Retired Feature Tables Are Retained, Not Dropped

**Recorded 9 September 2026 by build chunk 04, subchunk 04B (US-30).**

Withdrawing the check-in, SOS and family-contact behavior drops no table and
deletes no row. `check_ins`, `check_in_notifications`, `sos_alerts`,
`sos_notifications`, `family_contacts` and `destination_geofences` keep their
current definitions and contents, and chunk 04 adds no migration.

Two reasons. The check-in disposition is still a **proposed default owned by
founder/product** under [SCOPE-DISPOSITION.md](implementation/SCOPE-DISPOSITION.md),
so its data must survive until that is confirmed. And the rows are personal data
whose deletion belongs to the approved retention policy, not to a feature
removal — the plan for that is
[retirement/RETENTION-PLAN.md](implementation/retirement/RETENTION-PLAN.md),
which is a dry run and executes nothing.

Schema removal follows the migration sequence in
[IMPLEMENTATION-PLAN.md](implementation/IMPLEMENTATION-PLAN.md) §7 Phase 1 and
happens only after compatibility requirements end.

### Scheduled work withdrawn

These Celery beat entries are removed: `enqueue-due-checkin-fallbacks`,
`enqueue-pending-checkin-notifications`, `enqueue-pending-sos-notifications`
and `enqueue-due-sos-fallbacks`. Four of them polled every 10–30 seconds.

Their **task names stay registered as refusals** that dispatch nothing and open
no database session. Deleting the names outright would leave a beat process
still running the previous schedule, or a message queued before the deploy,
hitting an unregistered task and crashing its worker in a retry loop. The
retention sweeps `null_checkin_locations` and `delete_sos_alerts` continue to
run: retiring a feature must not switch off data minimization for the data it
leaves behind.

## 6.44 Amendment — Core Domain Identities and Separated States (US-28)

**Recorded 9 September 2026 by build chunk 05.** Additive only: revision
`0027_core_domain_model` creates nine tables and alters nothing. No existing
column changes, no row is written, no table is dropped.

### Why the legacy shape cannot carry the reset

`packages` is one row playing four parts — the purchase, the entitlement, the
provisioning job and the thing that expires — keyed off a single `status` whose
values mix payment (`pending`), lifecycle (`active`, `expired`) and commercial
outcome (`cancelled`, `superseded`). `esim_profiles.status` does the same for
three more questions: `issued` is the supplier, `downloaded` is the handset,
`activated` is the network. And every amount is NGN by construction —
`ngn_price`, `amount_ngn`, `total_ngn` — because that was the only currency sold.

None of that survives an enterprise buying lines in USD for staff who are not
the payer.

### The identities

| Table | Identity | Notes |
|---|---|---|
| `legal_entities` | **seller** | **No row is seeded.** Which entity sells is D3, open. |
| `users` | **payer** or **recipient** | Existing table, reused. |
| `organizations` | **payer** | Existing table, reused. |
| `products` | product | What is sold, independent of price. |
| `product_prices` | price version | Append-only, currency-explicit, per seller. |
| `orders` | order | Names its seller and exactly one payer; charge and settlement amounts remain separate. |
| `order_items` | order item | One independently recoverable line; names its recipient, which may be null until assigned. |
| `entitlements` | entitlement | What the holder is owed, in exact units. |
| `esim_installations` | eSIM installation | Links an entitlement to a device state. |
| `carrier_lines` | carrier line | Activation and network attachment. |
| `assigned_numbers` | assigned number | Live assignment unique; history preserved. |

Payer and recipient are **roles on a purchase, not new party tables**. Inventing
a `parties` table would duplicate identity that `users` and `organizations`
already own; a role belongs to the relationship.

### The states, and why they are separate columns on separate tables

| Resource | Column | Question |
|---|---|---|
| `orders` | `payment_state` | did anyone pay |
| `order_items` | `provisioning_state` | did the supplier fulfil it |
| `esim_installations` | `installation_state` | is the profile on a device |
| `carrier_lines` | `activation_state` | is the line live with the carrier |
| `carrier_lines` | `network_state` | is it attached right now |

They can disagree, which is precisely why one ordered status has to lie about at
least one of them. A paid order may be pending provisioning; a profile can be
installed on a handset that never attaches; a line can be suspended with the
profile still installed.

`provisioning_state` carries **`outcome_unknown`** as a first-class value. A
supplier request whose response was lost is not a failure and must never be
retried as a fresh purchase — it is reconciled against the same
`order_items.operation_reference`, which is written before dispatch. Chunk 11
owns that recovery; the state exists so it has somewhere truthful to sit.

Each order item has `quantity = 1` by database constraint. Bulk purchases use
one item per line because recipient, entitlement, supplier operation and
provisioning recovery are all line-specific; one shared item could otherwise
charge for several lines while recording only one outcome.

`network_state` defaults to `unknown` and is never inferred from activation.

### Money and exact units

Amounts are `NUMERIC(20, 6)` with a required ISO 4217 `currency` column beside
them, constrained to `^[A-Z]{3}$`. There is no default currency and no bare
amount. Rates get `NUMERIC(20, 10)`, because rates multiply and their error
compounds through a conversion chain.

Six decimal places is chosen for metered usage, not for display. **Presentation
scale is per currency** — NGN and USD present two places — and rounding for
display happens at the edge, never in storage. An order item has a composite
foreign key to its parent order's id and currency, so a mixed-currency order is
rejected by PostgreSQL. Chunk 10 applies the same by-construction rule to ledger
balances and postings.

`orders.currency` and `orders.total_amount` record what the customer was
charged. Nullable `settlement_currency` and `settlement_amount` record what the
seller receives after the processor settles. They are an atomic pair: both are
null until settlement is known, and otherwise both are present. This preserves
a USD charge and an NGN settlement as distinct values instead of overwriting or
adding them.

Entitlements are counted in **bytes and seconds**, not gigabytes and minutes.
The legacy `NUMERIC(6,2)` gigabyte balance cannot represent a supplier's
byte-level usage report without rounding, and rounding a balance against the
customer is a billing defect.

The currency and E.164 CHECK constraints are emitted **for PostgreSQL only**
(`ddl_if(dialect="postgresql")`), because `~` is not SQLite syntax and the fast
unit suite builds its schema on SQLite. Anything relying on them is therefore
tested against PostgreSQL in `tests/test_core_domain_postgres.py`.

### Preserved history

`pricing_tiers.ngn_price`, `transactions.amount_ngn`, `manifest_orders.total_ngn`,
every processor reference, receipt, package balance and issuance job keeps its
exact value. Proved by `tests/test_core_model_upgrade_postgres.py`, which
populates a database at revision `0026_i18n_locales` with a personal user, an
HTO organization, a paid manifest order, a package with its NGN transaction, an
issued eSIM profile and a pending issuance job, upgrades, and asserts the
snapshot is unchanged — then downgrades and asserts it again.

### Migration phases

The nullable → backfill → constrain sequence, and what is deliberately deferred,
is in [implementation/CORE-MODEL-UPGRADE.md](implementation/CORE-MODEL-UPGRADE.md).

---

## 6.45 Amendment — Email-First Account Identity and Session Versioning (US-29)

**Recorded 10 September 2026 during independent chunk 06 review.** Revision
`0028_account_identity` introduces `account_identifiers` and `identity_tokens`
and makes `users.phone_number` and `users.platform` nullable. This is required
for the adopted email-first account path: an account may exist before it has a
phone number, SIM, or mobile platform.

`account_identifiers` always belongs to a user. A partial unique index permits
only one verified owner for each normalized `(kind, value)`, while unverified
claims do not block the real owner. A second partial unique index permits only
one primary identifier per user. Confirming an email makes it primary, demotes
the former primary, and synchronizes the legacy `users.email` projection.

`identity_tokens` stores only a SHA-256 token hash. Its purpose is one of
`verify_identifier`, `recover_account`, or `authenticate`; the target kind and
normalized value are stored with the requested locale. `user_id` is nullable
only for an authentication token issued before a new email account exists.
The token is consumed atomically and expires at the exact `expires_at` boundary.

`users.auth_version` is a nonnegative integer starting at zero. Consumer access
and refresh JWTs carry that version. Recovery locks the user, increments the
version, revokes persisted refresh rows, and then issues the replacement pair;
therefore already-issued stateless access tokens stop working immediately.
Tokens minted before this column existed are interpreted as version zero so
existing sessions remain usable until recovery.

The migration backfills every existing non-null `users.phone_number` as a
verified primary phone identifier without changing the number or account.
When a passwordless login proves an email already stored on exactly one legacy
user, that address is adopted by the existing account rather than creating a
duplicate customer. An address shared by multiple legacy rows is treated as
ambiguous and requires support-assisted resolution.
Upgrade and legacy-only downgrade are exercised against a populated revision
`0027_core_domain_model` database. Once an email-only user exists, downgrade to
the non-null revision requires an explicit account migration; silently
inventing a phone or platform would corrupt identity data.
---

## 6.46 Amendment — Calling domain extension proposal (US-45/US-46)

9 September 2026. Governed by the [approved calling expansion](./implementation/VOICE-EXPANSION.md).

V02/V03 own future additive call-attempt, provider-leg, grant, event-inbox and
settlement changes through the shared ledger. Every attempt binds immutable
owner/tenant/payer/seller/currency, entitlement, destination, authorized identity,
rate version and reservation. Internet-only service must not need an eSIM/carrier
line. Preserve quantity-one recipient order items, historical calls and financial
rows. These are design requirements; no new table or migration is implemented
by this amendment. Detailed shapes precede the owning migration.

---

## 6.47 Amendment — Organization Memberships, Invitations and Second Factors (US-29)

**Recorded 10 September 2026 by build chunk 07.** Additive: no column is
dropped, no row is deleted, and `organizations.email` / `password_hash` are left
exactly as they are. Migration `0029_organization_memberships`.

### Why the legacy shape cannot carry the reset

An organization had one email and one password hash on `organizations`.
Everyone who administered the account shared them. That single fact produces
every one of US-29's failures at once:

| Question | Answer under the shared credential |
|---|---|
| Who did this? | Unanswerable — every action has the same actor |
| Can one person's access be removed? | Only by changing everyone's password |
| Can a second factor be required of somebody? | No — there is no somebody |
| Can two organizations share a person? | Only by that person holding two passwords |

`prd.md` §10 US-29 requires memberships, roles, invitations, administrator MFA
and immediate revocation. None of them are expressible without an individual
principal, so this amendment adds one.

### The tables

| Table | What it answers |
|---|---|
| `organization_members` | What may this person do in this organization, right now |
| `organization_invitations` | Who has been offered a role, and is that offer still live |
| `user_mfa_credentials` | *Can* this person prove a second factor |
| `mfa_recovery_codes` | Single-use fallbacks for a lost authenticator |
| `organization_elevations` | *Have* they proved it, for this tenant, recently |

#### `organization_members`

One row per `(organization_id, user_id)` pair, for the life of the pair, under
`uq_organization_members_pair`. Revocation is a `status` change with
`revoked_at`, never a delete — a deleted row cannot explain why an order placed
last month was authorized, and re-adding someone would otherwise race the row
that was supposed to be gone. The unique constraint is also what makes an
invitation replay safe: two simultaneous acceptances both see "not a member
yet", and only one insert survives.

`ck_organization_members_revoked_at` ties `status` and `revoked_at` together, so
a revoked row without a timestamp — or an active row carrying one — cannot
exist.

#### `organization_invitations`

`invited_kind` + `invited_value` (normalized by
`app.identity.service.normalize`, the same normalisation §6.45
applies to `account_identifiers`) is the **binding**. Acceptance requires the
accepting account to hold a *verified* identifier equal to that pair, so a
forwarded link, a leaked mailbox archive or a guessed id is worth nothing, and
an unverified claim on the address is worth nothing either.

`ux_organization_invitations_pending` is partial over `status = 'pending'`: at
most one live offer per address per organization, while accepted and revoked
rows remain as history. Reissuing after expiry atomically marks the old row
revoked before creating its replacement. `token_hash` stores only a SHA-256
hash. `ck_organization_invitations_revoked_at` prevents a revoked status and
its timestamp from drifting apart.

`ck_organization_invitations_bootstrap` ties `is_bootstrap` to a null token and
a null expiry — see the migration section below for why those two nulls belong
together and nowhere else.

#### `user_mfa_credentials` and `mfa_recovery_codes`

`ux_user_mfa_credentials_live` is partial over `status <> 'disabled'`: one live
credential per account. A second active secret is a second key to the same door,
and nobody audits keys they did not know about. Disabled rows are retained so
"this code was spent" keeps an answer.

An active credential cannot be replaced with the bearer token alone. It must be
disabled with a current TOTP or one of its single-use recovery codes first;
otherwise theft of the first-factor session would also replace the second
factor.

`last_used_counter` holds the highest TOTP counter already spent. A code is good
once, not for the whole thirty seconds it remains arithmetically valid — without
it, a code seen over a shoulder or in a screenshot is reusable for the rest of
its window.

**Open gap, deliberately not papered over:** `user_mfa_credentials.secret` holds
the raw shared secret. `security.md` §10.4 puts application-managed secret
material behind envelope encryption, which chunk 26 owns end to end — KMS, key
rotation and the decrypting service role. Encrypting it here with a key stored
beside it would look like protection and provide none, so the column is plain
and the gap is named. It is recorded in the chunk 07 handoff as an open item
for chunk 26.

#### `organization_elevations`

Scoped to `(user_id, organization_id, auth_version)`. The durable row, rather
than a JWT claim, makes membership and credential revocation immediate; binding
it to the account's login generation also means account recovery cannot issue a
new session that inherits a proof completed by the old session. Someone who
administers two tenants proves themselves for the one they are acting in; a
single proof authorizing both is exactly the confusion this scoping prevents.

### The controlled migration, and what it does not do

`0029` gives each existing organization **one pending owner invitation**
addressed to the contact already on its row. That is the entire promotion path,
and the exclusions are the substance:

- **No user account is created.** Manufacturing an account for an address
  nobody has proved is the auto-promotion AC-29.3's assignment forbids, and it
  cannot be undone by anyone who later turns out not to own the mailbox.
- **Nobody becomes an owner.** The organization gains its first owner when a
  person proves they can read that mailbox and claims the offer.
- **No `users` row is read for enrollment or promoted.** Historical customer
  accounts are customers. None of them is enrolled as organization staff.
- **Organizations that already have an active owner are skipped**, so a re-run
  cannot put a live tenant's ownership back up for grabs.

Bootstrap invitations carry no token and no expiry. A migration can neither send
mail nor know when someone will read it, so a seeded invitation with the
ordinary seven-day deadline would be dead before anyone saw it — and an expiring
bootstrap offer would lock every un-migrated organization out of its own
account. `ck_organization_invitations_bootstrap` confines both nulls to exactly
that case.

Verified by `tests/test_organization_migration_postgres.py`, which stands a
database up at `0027`/`0028`, seeds legacy organizations and customers, and runs
`alembic` for real — then downgrades and asserts chunk 06's backfill and every
pre-existing row survived.

### The shared credential is retained, and narrowed

`organizations.email` and `organizations.password_hash` still work, and still
open the manifest and reporting flows, so the dashboard keeps working until
chunk 22/25 migrates it. They no longer open anything privileged: every
permission in `STEP_UP_PERMISSIONS` is refused for a shared-credential session
(`shared_credential_forbidden`). Retiring the columns themselves is the last
step of the migration sequence in `implementation/IMPLEMENTATION-PLAN.md` §7 and
belongs to the chunk that retires the dashboard's login, not to this one.

---

## 6.46 Amendment — Supported-Market Catalog, Versioned Tariffs and Immutable Quotes (US-31)

**Recorded 10 September 2026 by build chunk 09.** Additive; migration
`0030_catalog_and_quotes`. No existing table is altered, no row is touched, and
**nothing is seeded**.

### Four countries, four columns

The legacy schema answered "where?" with `destination_country`. The reset needs
four different answers, and conflating any two of them is a real failure:

| Question | Table | Consequence of getting it from another column |
|---|---|---|
| Where may we **sell**? | `sales_markets` | Selling into a market nobody cleared |
| Where does the data **work**? | `product_coverage` | A plan that will not attach |
| Which number, from where? | `number_policies` | A number in the wrong country |
| Can this carry a **call**? | `provider_offerings` | The one `AGENTS.md` names |

That last one is the reason this is a table and not a boolean on `products`.
**Aggregate supplier data coverage is not native-voice eligibility.** A
supplier's data footprint across ninety countries says nothing about whether a
voice-capable profile can be issued in any of them, and selling a voice plan on
that basis produces a customer holding a line that cannot make calls.
`_offering_satisfies` in `app/catalog/service.py` is where that is refused, and
`test_a_data_only_supplier_cannot_satisfy_a_voice_plan` is where it is proved.

Every capability column defaults to **false**. An unverified capability is an
absent capability; defaulting to true would make each new offering claim
everything until somebody remembered to say otherwise.

### Publication is where the open decisions bite

`PublicationStatus` has a `VERIFIED` step between draft and published on
purpose. Recording that a market is real is a different act from deciding to
sell there, and collapsing them means the moment somebody files evidence the
product goes on sale.

Two CHECK constraints carry D2 and D3:

- `ck_sales_markets_evidence` — nothing leaves draft without an evidence
  reference and a verification timestamp.
- `ck_sales_markets_published_needs_seller` — nothing is published without a
  legal entity, and `legal_entities` is deliberately unseeded by §6.44.

So the open decisions express themselves as *things that will not sell*, rather
than as claims that later turn out to be false.

### Tariffs know where a call starts

`tariff_rates.origin_kind` distinguishes an **internet** origin from a **carrier
visited network**, which `VOICE-EXPANSION.md` requires. A tariff recording only
"origin: NG" could not tell a customer roaming in Nigeria on a carrier line from
one sitting in Lagos making an internet call, and those cost us different
amounts.

`select_rate` prefers an exact origin country over an any-origin wildcard, and
**never falls back across `origin_kind`**. Using a roaming rate because the
internet rate is missing prices a call at a number that describes a different
call.

`ux_tariffs_published` allows one live version per product and currency. Two is
not a pricing decision; it is a race about which one a quote happened to read.

### Quotes are immutable, and the database says so

A quote is the server's promise of a price, so `total_amount` being editable
would make it not a promise. `trg_quotes_immutable` refuses any `UPDATE` that
changes a priced column — only `status` and `redeemed_at` may move — and
`trg_quote_items_immutable` refuses every update to a line.

Writing the service against that trigger changed the service: `issue_quote`
originally inserted an empty quote and filled in the totals, which the trigger
correctly refused. It now builds the whole quote in memory and inserts once. A
constraint that changes how the code is written is the constraint working.

`quotes.digest` is a SHA-256 over the canonical serialisation of the quote and
its lines. It is belt to the trigger's braces: the trigger stops an `UPDATE`,
the digest catches rows reached another way — a restore, a manual `psql`
session, a migration with a bug in it. It hashes amounts **normalised to the
currency's exponent**, because the column is `Numeric(20, 6)` and a quote issued
as `1000.00` reads back as `1000.000000`; hashing the raw value made every quote
read as tampered after one round trip.

`ck_quotes_total_is_sum` and the digest catch different things, which is worth
stating because it is easy to think one is redundant. The constraint proves the
parts add up; the digest proves they are the parts the server issued. A subtotal
that no longer matches its own lines passes the first and fails the second.

### Rounding

`app/money.py` gains `currency_exponent`, `round_money` and `sum_money`.

- The exponent is the **currency's**, from ISO 4217 — JPY has none, KWD has
  three. An unknown code **raises** rather than defaulting to two: the default
  would undercharge by a factor of a hundred in a zero-exponent currency and the
  result would look like a pricing decision rather than a bug.
- Rounding is **half-to-even**, not half-up. Across many lines half-up drifts
  consistently in the seller's favour, and "we round in our own favour, a
  little, every time" is a question nobody wants to answer.
- A line is the **rounded** unit times quantity, and an order total is the sum of
  the rounded lines, so somebody adding up a receipt gets the number at the
  bottom.

### What is deliberately not here

No tax rate. `quotes.tax_amount` is zero and
`tax_configuration_reference` is null, because D3 is open and inventing a rate
would put a number on an invoice that no authority asked for. The column exists
so the treatment can be recorded by reference when it is decided, never inlined.

---

## 6.47 Amendment — Multi-Currency Ledger and Atomic Reservations (US-32)

**Recorded 10 September 2026 by build chunk 10.** Additive; migration
`0031_ledger_and_reservations`. `packages`, `transactions` and their NGN columns
are untouched.

### Why a ledger instead of a balance column

The legacy accounting was `packages.data_gb_remaining` and
`transactions.amount_ngn`: numbers that code decremented. That shape cannot
answer the two questions an accounting system exists for — *why* is the balance
this number, and does it still add up — and it loses money silently the first
time two requests decrement it at once.

### The invariants, and what enforces each

| Property | Enforced by |
|---|---|
| Every entry balances, per currency | `trg_journal_entries_balance`, a **deferred** constraint trigger |
| Posted history is never edited | `trg_journal_entries_immutable`, `trg_journal_lines_immutable` (UPDATE *and* DELETE) |
| One business event posts once | `uq_journal_entries_event` |
| No cross-currency arithmetic | Two composite foreign keys on `journal_lines` |
| A reservation cannot overspend | `SELECT … FOR UPDATE` on the account row |

The deferred trigger is the one worth understanding. A balanced entry cannot be
written by a single statement — the lines are inserted one at a time — so a
per-statement check would fail on the first line of every legitimate entry.
`DEFERRABLE INITIALLY DEFERRED` checks at COMMIT instead, which also means a
half-written entry cannot survive a crash: the whole balanced entry commits or
none of it does.

`business_event_id` is caller-supplied and meaningful (`order:<id>:capture`),
not a random UUID per attempt. A random id would make every retry a new event
and defeat the constraint entirely — the idempotency is in the *naming*.

### Balances are signed in the account's natural direction

`NATURAL_SIDE` records which side increases each account kind, and `balance()`
reports accordingly. A customer holding 1,000 of credit reads as `1000`, not
`-1000` because a liability happens to be credit-natured. Anybody reading a
balance wants the amount, not a lesson in sign conventions.

### Reservations are not postings

A hold does not move money. Nothing has happened to it — it is still the
customer's and still in their account — so a reservation reduces what is
*available* without touching the balance, and **releasing one posts nothing**.
Writing a journal entry for a released hold would invent a transaction that did
not happen, and the ledger would describe a refund nobody received.

Settlement is the only reservation operation that posts, because settlement is
where money actually moves. Partial settlement is normal — a call reserves a
maximum and settles what it cost — and the remainder stays held until the caller
releases it, because deciding on the customer's behalf that they are finished is
not the ledger's call to make.

### Closed loop

`SERVICE_CREDIT` is deliberately not called a wallet. There is no transfer
between customers, no cash-out and no foreign-exchange engine — each of those
turns a prepaid balance into a money-transmission product with a different
licensing conversation attached. Structurally: an account is identified by its
owner, so there is no operation that moves credit from one customer to another.

### The legacy backfill, and what it refuses to do

`app/ledger/backfill.py` is a re-runnable operation with a reconciliation
report, deliberately **not** a migration step. A backfill inside a migration
runs once, in a transaction nobody is watching, with no report anyone reads.

Each successful legacy transaction posts `settlement_clearing → revenue`, both
system accounts. Three refusals matter more than the posting:

- **No `SERVICE_CREDIT` is created.** The legacy product had no wallet: every
  payment bought one package outright, so no customer ever held a balance.
  Creating one would put a liability on the books that no event produced.
- **Leftover gigabytes are not converted to cash.**
  `packages.data_gb_remaining` is a *unit* balance. Converting it would apply a
  pricing decision nobody made, retroactively, to customers who never agreed
  to it. Entitlements belong to §6.44's table.
- **Entries post at `transactions.created_at`.** That is the only date the
  legacy table has — there is no payment timestamp, and `receipt_sent_at` is a
  different event, sometimes days later. Using it would be exactly the
  unsupported assumption about legacy rows the assignment warns against. What
  matters is that it is not the migration's own date: stamping everything
  "today" destroys the only thing a backfill exists to preserve.

The report carries both totals and the skipped counts, because a backfill that
reports only successes is one nobody can check.

---

## 6.48 Amendment — Durable Outbox, Supplier Attempts and Worker Leases (US-32)

**Recorded 10 September 2026 by build chunk 11.** Additive; migration
`0032_fulfilment_outbox`. The legacy `esim_issuance_jobs` path and its Celery
scheduling are untouched.

### The failure this exists for

`AGENTS.md` calls the accepted-but-response-lost case the single most expensive
failure mode in this product. The sequence is short: we ask a supplier to
provision a line, the supplier accepts and charges us, the response is lost. The
order still looks unfulfilled, and anything that retries naively buys a second
line for a customer who already has one.

### `outcome_unknown` is a state, not an error

`supplier_attempts.outcome` has five values, and the distinction between
`rejected` and `outcome_unknown` is the one that costs money. A definite refusal
is safe to treat as final. An absence of response never is — collapsing it into
"failed" makes it look retryable, and the retry buys the second line.

`held_for_review` is the fifth: reconciliation asked and the supplier could not
say. Guessing costs money one way or leaves a customer without service the
other, so a human decides.

### The ordering that makes recovery possible

The attempt row is written and **committed before** the supplier is called. A
crash between commit and call is then indistinguishable from a crash after the
call, and both reconcile identically. Calling first and recording afterwards
produces a purchase nobody has any record of.

### Two constraints do the real work

- `ux_supplier_attempts_live_item` — a partial unique index allowing one *live*
  attempt per order item, where live means `in_flight`, `accepted`,
  `outcome_unknown` or `held_for_review`. A second concurrent attempt is not a
  retry; it is a second purchase, refused in the database rather than in a code
  path somebody can forget to call.
- `uq_supplier_attempts_key` — `(provider, idempotency_key)`.

The idempotency key names **one request**: `order-item:<id>:attempt:<n>`. The
first version of this keyed on the order item alone, and writing the tests found
why that is wrong: a *legitimate* second attempt after a definite rejection
would reuse the key, and the supplier would de-duplicate the new purchase
against the old refusal. The order would never be fulfilled and nothing would
say why. A retry of the same request reuses the key; a new decision to buy gets
a new one.

### Outbox and inbox

`outbox_messages` is the transactional outbox: work is written in the same
transaction as the state change that caused it, so the instruction exists if and
only if the change did. A worker told to act before the database commits may act
on a state that then rolls back.

Claiming uses `FOR UPDATE SKIP LOCKED` under a **lease**, not a lock. A worker
that dies holding a lease loses it when the lease expires and the work becomes
claimable again — without which a crashed worker strands its message forever and
the order silently never completes, which is worse than failing because nothing
alerts.

`ck_outbox_messages_lease` ties `leased_until` and `leased_by` together: a lease
without a holder is a row no recovery logic can reason about.

`inbox_messages` is the same idea inbound. Every supplier and processor
redelivers; `(source, external_id)` is the identity, because providers number
their own events and "evt-1" from two of them is two different events.

### Cancellation loses to an outstanding request

Cancelling an item with a live attempt is **refused**. The supplier may be about
to accept, and marking the item cancelled produces a cancelled order with a
purchased line behind it. Reconciliation resolves the truth first. Cancelling an
item with no attempt also completes its queued outbox message, so a worker
claiming it later does not provision something already cancelled.

---

## 6.49 Amendment — Provider-Neutral Payment Contract (US-33)

**Recorded 10 September 2026 by build chunk 12.** Additive; migration
`0033_payment_contract`. `transactions` and the legacy Paystack/Flutterwave path
are untouched.

### Why a contract rather than a processor

**D4 is open.** No global processor is selected, Stripe is a candidate and not a
decision, and code naming one would have to be unpicked when the decision goes
elsewhere. `PaymentProcessorAdapter` is the whole surface a processor must
present, and nothing above it knows which one it is talking to.

### Intent and attempt are separate

An order has at most one `payment_intent` — the business intention to collect —
and an intent may have several `payment_attempts`: a card declined, then a bank
transfer. Separating them is what makes double-capture **detectable**: two
successful attempts against one intent is a fact the database can see, rather
than two unrelated payments nobody correlates.

Four fields on an intent never change: seller, merchant account, currency, and
the order and quote it pays for. PostgreSQL rejects intent updates and binds
merchant id, seller and currency with one composite foreign key. Service code
also requires the intent amount to equal the order total. An attempt needing
different values is a new attempt, not an edit.

### `ux_payment_attempts_one_success`

A partial unique index over `status = 'succeeded'`, one per intent. Two
successful charges for one order is the failure this chunk exists to prevent,
and this refuses it rather than reporting it afterwards.

Only one created, pending or unknown attempt may be live for an intent. Attempt
creation locks the intent, and `(processor, idempotency_key)` is unique. Capture
also locks the intent, so two different late successes serialize: one pays the
order and the other is durably recorded as excess.

### Excess payments are recorded, never dropped

A charge that cannot be matched — wrong amount, wrong currency, unknown
reference, or an order already paid — becomes an `excess_payments` row rather
than a discarded webhook. The customer's account has already been debited, and
refusing to write it down would be losing their money. Chunk 14 refunds them.

Dropping the webhook is the alternative, and the alternative is a customer who
has been charged twice and a system that has never heard of the second charge.
The stored evidence is an allowlist of reference, status, amount, currency,
merchant reference and event name. The provider's raw customer and
authorization objects are not retained.

### A redirect cannot mark an order paid

`payment_state = PaymentState.PAID` is assigned in exactly one place,
`PaymentRouter.capture`, which takes a `ProcessorCharge` the caller has already
verified. A browser return URL is a message from the customer's own browser and
anyone can navigate to a URL; it is a hint to show a spinner, never evidence
that money moved. There is a test asserting that single assignment exists in
that one place.

### Live collection is disabled, structurally

`merchant_accounts.live_enabled` defaults to false, and
`ck_merchant_accounts_live_needs_approval` refuses to let it be true without a
named `approval_reference`. That constraint is where "keep live collection
disabled pending D3/D4" stops being a promise. Sandbox work stays possible
through an explicit `require_live=False`, so it cannot happen by accident.

### Routing inputs

Seller, currency and method — never nationality, never an IP address. Both of
those are guesses about a person; a merchant account is a fact about who may
legally take their money in that currency, and routing on a guess is how a
customer is charged through an entity with no relationship to them.
`merchant_payment_methods` is the explicit method capability; an account that
has not enabled a rail cannot be selected for it, and multiple eligible
accounts are an ambiguity error rather than an arbitrary first row.

### Paystack, conditionally

`app/payments/paystack_adapter.py` implements the contract for **NGN only** and
refuses any other currency rather than converting — a quiet conversion would be
a foreign-exchange decision this product has not made.

The amount is sent as a string in the currency's minor unit with the exponent
**derived** from `app/money.py` rather than hardcoded as 100. A payer email is
required before transport, metadata is JSON encoded, and locally generated
references use only Paystack's documented character set. Missing reference,
amount, currency or status in a response is rejected rather than defaulted.

Vendor behaviour is documented rather than assumed: the endpoints, the
minor-unit convention and the `x-paystack-signature` HMAC SHA-512 scheme are
cited to Paystack's public API reference, **checked 10 September 2026**. No live
or sandbox call has been made, and the adapter tests are not evidence that
Paystack behaves as documented.

---

## 6.50 Amendment — Refunds, Disputes, Bank Funding and Receipts (US-34)

**Recorded 10 September 2026 by build chunk 14.** Additive; migration
`0034_refunds_and_reconciliation`. Nothing seeded, no existing row touched.

### Money going out is not the mirror of money coming in

| Table | Why it is its own table |
|---|---|
| `refunds` | Bounded by a specific captured charge, not by an order total |
| `disputes` | The bank took the money and told us afterwards — a different event with a different accounting treatment |
| `bank_transfer_receipts` | Evidence, imported separately from the decision to credit anybody |
| `financial_documents` | Facts frozen at issue, never regenerated |
| `processor_settlement_reports` | Immutable processor gross, refund, dispute, fee, tax, FX and payout evidence |
| `exception_items` | What a human has to look at, with enough context to act |

### The refund ceiling

**Total refunded can never exceed the refundable charge.** Exceeding it is not a
large refund; it is a payout, and a payout is a different product with a
different licensing conversation attached.

It spans rows, so it is not one constraint. `request_refund` computes the
remaining headroom under `SELECT … FOR UPDATE` on the payment attempt, so two
concurrent partial refunds cannot both see the same room. Chunk 10's balance
trigger independently proves that each settled refund posting balances; a
balanced journal entry by itself cannot enforce this cross-row ceiling.

**An in-flight refund counts against the headroom.** A refund whose outcome we
have not seen may already have paid out, and excluding it is exactly how a
second refund gets authorized on top of a first.

### A refund posts only when it settles

A refund that has not settled has not moved money. Posting on request would show
a reversal before the customer's bank saw anything. A successful processor
capture posts `settlement_clearing → revenue`; when its refund settles, the
refund posts the opposite `revenue → settlement_clearing` entry under its own
business event. Neither path edits history, which chunk 10's trigger refuses
anyway. A customer service-credit account is not used as a stand-in for an
external cash refund.

### A dispute is not a refund

A chargeback is the bank taking money back and telling us. Recording it as a
refund would make the books say we chose to give it back. A **lost** dispute
posts the loss to `adjustment`; a **won** one posts nothing, because the money
never left and a reversal of a reversal invents two transactions that did not
happen.

Whether a lost dispute claws back the customer's remaining allowance is a policy
question — **D5 is open** — so this chunk records the money and does not decide
the service consequence.

### Bank funding is reconciled evidence, not a screenshot

`uq_bank_transfer_receipts_line` makes re-importing a statement harmless, which
is the failure a manual funding process produces every time.

Importing and crediting are **separate acts**. An import credits nobody;
matching names both the account and `matched_by`, because a funding credit with
no attributable decision is indistinguishable from the unaudited balance edit
the assignment forbids. An unmatched line stays imported, uncredited, and goes
to the exception queue — guessing whose payment it is credits one customer with
another's money.

The database requires a matched row to carry the account, actor and match time,
and binds the account currency to the receipt currency. Once matched, the row is
immutable; a correction is new evidence, not a rewrite of bank history.

Funding posts at the bank's **value date**, not the date somebody got round to
reconciling it.

### Documents are frozen

`financial_documents.snapshot` holds the amounts, currency, seller and tax
reference the document states, **copied rather than referenced**. A receipt
regenerated from live data next year would show next year's prices with this
year's date, and a customer comparing it against their bank statement would be
right to complain. Numbers are unique per seller and kind: a tax authority
asking for invoice 47 must get exactly one document.

Issued documents are immutable at the database boundary. Refunds and disputes
are structurally bound to the processor and currency of their payment attempt,
and terminal outcomes are immutable as well, so a late callback cannot rewrite
a settled refund or a lost chargeback.

`processor_settlement_reports` stores each imported report once under its
processor reference. Reconciliation compares the report's gross captures,
refunds and lost disputes with local records for the same processor, currency
and half-open period. It independently verifies their clearing and
revenue/adjustment ledger postings, then checks the report's fee, tax, FX and
net-payout arithmetic. Every difference enters `exception_items`. The import
snapshot and all economic columns are immutable.

This closes the fixture/software contract, not the provider decision. Actual
report formats, fee schedules, tax policy, FX terms and live evidence remain
blocked on D3/D4/D5. The older `settlement_report` helper remains an
expected-net local aggregation and is not presented as processor evidence.

### The exception queue

`exception_items` is the interface chunk 25 builds its operations screens on.
Every row names its kind, its subject and why — an exception queue whose rows do
not explain themselves is a list people learn to ignore. `sweep_excess_payments`
turns chunk 12's recorded excess into something somebody actually sees: an
excess payment nobody looks at is a customer charged twice and never refunded.
