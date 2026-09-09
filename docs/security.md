# Security & Compliance Specification

> **Current scope:** the September 2026 reset in §10.14 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

# DamDam — Version 0.1

## 10.1 Scope and Governing Framework

Primary framework: Nigeria Data Protection Act (NDPA) 2023, as the
controlling entity is Nigerian-incorporated (or the Nigerian OpCo,
per the entity structure detailed in
[`corporate-structure.md`](./corporate-structure.md)) and the
majority of data subjects are Nigerian citizens. Saudi Arabia's
PDPL is a secondary consideration since location data is captured
while pilgrims are physically in-country, though the data
controller relationship remains with DamDam, not a Saudi entity,
for MVP scope.

**This document is a first draft, not a substitute for
professional legal review.** Given the founder's GRC background,
treat this as a working draft to tighten rather than a finished
artifact — flagged throughout where a legal professional's sign-off
is the actual gating step.

### 10.1.1 Compliance Strategy: GDPR Baseline + NDPA-Specific Requirements

The NDPA 2023 is the law governing DamDam today: the controlling entity is
Nigerian-incorporated and the current product serves Nigerian data subjects.
GDPR does not currently apply extraterritorially because DamDam neither has EU
data subjects nor offers goods or services to people in the EU.

DamDam will nevertheless use GDPR's substantive rigor as its engineering
baseline: data minimization, purpose limitation, storage limitation,
lawfulness, fairness and transparency, and data-subject rights. The NDPA is
explicitly modeled on GDPR and shares the great majority of those principles,
so this baseline addresses nearly all of the NDPA's substantive requirements
while preparing the product for possible international expansion.

This decision does **not** adopt GDPR-exclusive administrative machinery before
GDPR actually applies. DamDam will not speculatively appoint an EU
representative under Article 27, adopt Standard Contractual Clauses or another
EU cross-border transfer mechanism, or maintain formal Article 30 Records of
Processing Activities. Revisit those deferrals only when either:

1. DamDam begins serving EU-resident users, including Nigerian diaspora users
   in Europe; or
2. a real investor due-diligence requirement makes GDPR readiness a concrete
   near-term need.

Neither trigger currently exists. This follows the same implement-on-trigger
discipline used for the IDT BYOC and Stripe/Adyen deferrals in
`scaling-infrastructure.md` §12.9.1 and §12.6.

GDPR alignment is not a substitute for NDPA-specific obligations. In
particular, mandatory NDPC registration and the NDPA's broader breach
notification threshold remain separate action items tracked in §10.10 and
§10.8 respectively. This strategy does not change the retention periods in
§10.3: the documented 90-day check-in location nulling, 3-year SOS retention,
30-day account-deletion grace period, and the other stated periods already
implement the storage-limitation principle.

---

## 10.2 Data Classification

| Category | Examples (from data-model.md) | Classification |
|---|---|---|
| Direct identifiers | `phone_number`, `first_name`, `last_name`, `email`, `passport_number` | PII — high sensitivity |
| Authentication secrets | `pin_hash`, `password_hash`, JWT refresh tokens | Sensitive — credential material |
| Location data | `check_ins.latitude/longitude`, `sos_alerts.latitude/longitude` | PII — high sensitivity, special-category-adjacent given it can reveal religious pilgrimage activity |
| Communications metadata | `call_logs` (to_number, duration, timestamps) | PII — medium-high sensitivity |
| Financial | `transactions` (amount, payment method — **not** full card numbers, which never touch DamDam's systems, see §10.7) | Sensitive — financial |
| Device/technical | `device_compatibility_log` (device model, OS version, platform) | Low sensitivity |
| Business data | `hto_operators`, `manifests`, `pricing_tiers` | Low-medium (business confidential, not personal) |

**Special note on location + religious inference:** Because this
product's core use case is Hajj/Umrah travel, location data
combined with timing can reveal that a person undertook a
religious pilgrimage. In some jurisdictions and threat models,
religious affiliation data carries elevated protection
requirements. This should be explicitly named in the privacy
policy and treated with the same rigor as special-category data
even where NDPA doesn't formally mandate it — the reputational and
trust cost of mishandling it is severe for exactly the population
this product serves.

---

## 10.3 Data Retention

| Data type | Retention period | Rationale |
|---|---|---|
| `check_ins` (location) | 90 days post-trip `expires_at`, then location fields nulled (row retained for aggregate analytics minus lat/lng) | Operational need ends at trip conclusion; no legitimate reason to retain precise pilgrim movement history long-term |
| `sos_alerts` | 3 years, full retention including location | Potential legal/insurance/liability relevance; SOS events are rare and high-stakes enough to warrant longer retention |
| `usage_polls` | 30 days raw, then collapsed to daily summary | High volume, low individual-record value after balance reconciliation is complete |
| `call_logs` | 12 months | Billing dispute window + reasonable audit trail |
| User account data (post-deletion request) | 30-day soft-delete grace period, then hard delete | Balances accidental-deletion recovery against the right to erasure |
| `device_compatibility_log` | 24 months, PII-stripped after 90 days (device model retained, `user_id` link removed) | Aggregate product analytics value persists after the individual link is no longer needed |
| Payment transaction records (automated and manually confirmed HTO invoices) | 6 years | Standard financial record-keeping (tax/audit), independent of NDPA. Stored webhook evidence is the minimized reconciliation subset in §10.13, never the full provider body. |
| WhatsApp message logs | Governed by the WhatsApp Business API provider's own retention, not DamDam's — documented dependency, not assumed control | |

**Action item flagged for founder review:** the 3-year SOS
retention and 6-year financial retention figures are reasonable
defaults, not researched Nigerian-specific legal minimums — verify
against NDPA's actual retention guidance and any CBN record-
keeping rules for payment data before this becomes final policy.

---

## 10.4 Encryption

**In transit:** TLS 1.2+ enforced on all endpoints (via Cloudflare
Tunnel termination, see infrastructure.md §11.2). No plaintext
HTTP path should exist, including internal service-to-service
calls where feasible.

**At rest:**
- Postgres: encryption at rest via underlying disk/volume
  encryption (OCI block volume encryption — verify explicitly
  rather than assuming default-on)
- `pin_hash`, `password_hash`: bcrypt (cost factor 12 minimum),
  never reversible, never logged
- JWT refresh tokens: stored hashed (SHA-256) in Postgres, not
  plaintext, even though they're already opaque tokens — defense
  in depth against a database dump exposing usable session tokens
  directly

**Application-level field encryption:** Consider column-level
encryption for `manifest_pilgrims.passport_number` specifically —
a high-value identity document number with a narrow legitimate use
case (NAHCON compliance documentation only) that doesn't need to
be queryable, making it a good candidate for encrypted storage
where only specific service roles can decrypt.

---

## 10.5 Authentication & Authorization Matrix

| Actor | Can access | Cannot access |
|---|---|---|
| Pilgrim (own account) | Own profile, own packages, own check-ins/SOS/calls | Any other pilgrim's data; HTO or admin endpoints |
| HTO Operator | Pilgrims within their own manifests only; their own manifest/order data | Other HTOs' manifests or pilgrims; admin endpoints; pilgrim data outside their own manifests |
| Admin | All data, via the 4 scoped admin screens | N/A for MVP — single admin role. **Flag:** as the team grows, subdivide (e.g., a support-only admin without financial data access) — not needed at MVP headcount but the `admin_users.role` enum is kept extensible now rather than hardcoded |
| Family Contact | Nothing (no account, no login — outbound WhatsApp only) | Everything |

**Cross-tenant isolation enforcement:** Every HTO-scoped query
must filter by `hto_operator_id = current_user.hto_operator_id` at
the query level, not just the UI level. This is a standard
multi-tenancy failure mode worth stating explicitly as a
non-negotiable code review checklist item — a missed filter on
even one endpoint leaks one HTO's pilgrim list to another.

---

## 10.6 KYC / Verified Caller ID Data Handling

**⚠ Requires founder/legal review before final — flagged as thin
by design, needs confirmation against actual Nigerian regulatory
expectations, not assumed sufficient by this draft.**

Given the CLI verification flow (OTP against the pilgrim's
registered number via the configured OTP provider — Termii
primary, Twilio Verify secondary — reused from the login flow,
prd.md §5.1/§5.5):

- The verification event (`caller_id_verifications` table) stores
  only the reporting provider name, its opaque verification
  reference, and a timestamp — no OTP code is ever persisted after
  verification completes (the provider handles generation/
  validation entirely; DamDam never sees the code itself)
- This is a deliberately thin data footprint — DamDam is not
  collecting or storing government ID documents for CLI
  verification, since Nigeria's NCC framework for legitimate CLI
  display requires proof of number ownership, not identity
  document verification
- **Compliance note requiring direct review:** confirm this
  thin-KYC approach is sufficient for Nigeria's specific
  requirements around CLI display, rather than assuming the
  OTP-ownership-proof standard used by Western CPaaS providers
  translates directly to Nigerian regulatory expectations

---

## 10.7 Third-Party Data Processors

| Processor | Data shared | DPA status needed |
|---|---|---|
| Termii | Phone numbers, OTP delivery metadata (primary OTP provider) | Confirm explicit DPA availability |
| Twilio | Phone numbers, OTP delivery metadata (secondary/failover OTP provider only — no longer the voice vendor, see `prd.md` §5.5) | Twilio's standard DPA — review and countersign |
| Telnyx | Phone numbers, call metadata, verification events (voice/PSTN vendor) | Confirm explicit DPA availability |
| Paystack | Payment amounts, transaction references, email (optional) — **not** full card numbers (Paystack is PCI-DSS compliant, card data never transits DamDam's servers) | Confirm explicit DPA availability |
| Flutterwave | Same data profile as Paystack — automatic fallback processor only (`data-model.md` §6.7), not a routine second collection channel, but a real processor relationship requiring the same DPA diligence regardless of how rarely it's actually invoked | Confirm explicit DPA availability |
| Monty Mobile / eSIM Access / 1Global | No PII required for eSIM issuance for MVP (profiles aren't identity-tied at the aggregator level) — confirm this holds for the specific vendor actually serving a given profile (any of the three, per the cascading failover in `data-model.md` §6.6), since some destinations require passport data for regulatory reasons | DPA needed if any PII does flow, for each of the three |
| Meta (WhatsApp Business API) | Phone numbers (pilgrim, family contact, HTO operator), message content (check-in/SOS notifications) | Meta's Business Data Processing Terms — accepted through Business API onboarding |
| Cloudflare | Traffic metadata, R2-stored files (CSV manifests, QR images) | Cloudflare DPA, standard |
| Oracle Cloud Infrastructure (OCI) | Full database contents (self-hosted Postgres, per `infrastructure.md` §11.2/§11.3 — Supabase was considered and dropped, so OCI is now the sole infrastructure holder of all pilgrim PII, not just the application layer) | OCI's standard cloud services agreement; confirm it includes adequate data processing terms for NDPA purposes given OCI now holds significantly more sensitive data than when it was "just" the compute host |
| Resend | Email addresses, email content | Resend's DPA |
| Apple / Google (App Store, Play Store) | Developer account data, app usage analytics per platform terms | Standard platform developer agreements — not a data processor relationship in the traditional sense but worth including in the compliance inventory |

**Action item:** compile signed/accepted DPAs into a single
compliance folder before processing any real pilgrim data — a
pre-launch checklist item, given NDPA's processor-accountability
requirements.

---

## 10.8 Incident Response

**⚠ Response outline requires expansion with founder's GRC
expertise — left at framework level here, not a finished plan.**

**Trigger conditions:**
- Suspected unauthorized database access
- A third-party processor reports a breach affecting DamDam's data
- Discovery of a cross-tenant data leak (§10.5)
- Loss of an admin credential

**Response outline:**
1. **Contain** — revoke affected credentials/tokens immediately,
   isolate affected systems
2. **Assess** — scope of data affected, number of data subjects
3. **Notify** — NDPA requires notification to the Nigeria Data
   Protection Commission within a specified window (confirm exact
   timeline — this is the kind of detail requiring direct
   regulatory citation, not left as a draft assumption). **Build the
   incident-response trigger to the NDPA's broader standard:** it covers an
   incident leading to *or likely to lead to* unauthorized access, loss, or
   disclosure. GDPR's (and the former NDPR's) breach definition lacks that
   "likely to lead to" language. A narrower, GDPR-calibrated trigger could
   under-report incidents that the NDPA requires DamDam to notify, so the
   outstanding detection and notification tooling must not use it.
4. **Notify affected users** — particularly urgent given the
   population may be traveling internationally with limited
   connectivity at notification time; WhatsApp is likely the most
   reliable channel of last resort given its near-universal reach
   for this demographic
5. **Remediate and document**

**Hajj-season-specific consideration:** An incident during the
actual Hajj period (mid-May 2027) is the worst-case timing — users
are abroad, harder to reach, and potentially in a heightened-stress
environment already. A specific tabletop exercise before the
season is worth doing, not just a generic written plan.

---

## 10.9 Location Data — Specific Safeguards

- Location is only ever collected on explicit user action
  (check-in tap, SOS trigger) — no background/continuous tracking
  exists in MVP scope (consistent with prd.md NG1)
- Location permission request copy must clearly explain purpose
  ("Used only when you tap check-in or SOS, to help your tour
  operator find you") — not a generic OS permission dialog with no
  context
- HTO operators see location only for their own manifested
  pilgrims, only in the context of a specific check-in/SOS event —
  never as an aggregated movement history or map overlay. No
  "see everyone's location on a map" feature exists, deliberately,
  both for MVP scope and because it would be a meaningfully more
  invasive feature than what's specified

---

## 10.10 Pre-Launch Compliance Checklist

- [ ] Privacy policy published, covering all data types in §10.2,
      retention periods in §10.3, and the religious-inference
      consideration
- [ ] Terms of Service covering the family contact's one-way,
      no-consent-required notification basis — worth specific
      legal attention, since the family contact is a data subject
      who never directly consents to DamDam processing their
      number
- [ ] All processor DPAs in §10.7 signed/accepted
- [ ] Mandatory NDPC registration/compliance filing completed
- [ ] Incident response plan reviewed and tabletop-tested
- [x] Data retention automation (the deletion jobs implied by
      §10.3) built and tested, not just documented
- [ ] Apple App Store and Google Play privacy label/data safety
      disclosures completed accurately (both platforms require
      declaring data collection categories at submission — this
      needs to match §10.2's classification exactly, or app review
      can be rejected/delayed)

---

## 10.11 Amendment — GDPR Baseline Without Premature GDPR Administration

This amendment formalizes the compliance strategy in §10.1.1: the NDPA governs
DamDam's present Nigerian operations, while GDPR's substantive principles are
the engineering baseline. GDPR-only administrative mechanisms remain deferred
until an EU-resident-user or concrete investor-diligence trigger exists.

It also clarifies that NDPC registration and the NDPA-specific breach threshold
remain independent obligations, and changes §10.8's future tooling requirement
to detect incidents that are *likely to lead to* unauthorized access, loss, or
disclosure. No retention duration in §10.3 is amended; those periods already
align with the storage-limitation principle.

---

## 10.12 Amendment — Data Retention Automation Implemented

The §10.3 schedule is implemented as independent daily Celery Beat tasks for
check-in location nulling, SOS deletion, usage-poll aggregation, call-log
deletion, post-grace-period account deletion, device-link stripping, device-log
deletion, and transaction deletion. Each changed top-level row writes an atomic
`data_retention` audit entry with a deterministic idempotency key; an immediate
rerun neither changes the row again nor duplicates its audit record. A shared
PostgreSQL advisory lock serializes overlapping retention sweeps.

Account deletion begins with `DELETE /me/account`, which revokes refresh tokens
and starts the 30-day soft-delete grace period. Hard deletion removes the user
link but does not prematurely delete SOS alerts, check-in aggregate rows, call
logs, device compatibility analytics, or payment transactions; their own
retention rules remain authoritative. Raw usage polls are collapsed into one
UTC daily summary per pseudonymous eSIM-profile identifier before deletion;
neither raw nor summarized usage cascades with account-owned eSIM rows. The
device log uses two separate actions: remove `user_id` at 90 days and delete
the row at 24 months.

No WhatsApp retention task exists because Meta, not DamDam, governs those
provider-side message logs. This amendment implements the existing periods
exactly; it does not resolve or alter the founder/legal verification action for
the 3-year SOS and 6-year financial defaults.

---

## 10.13 Amendment — Minimized Payment Evidence and Complete HTO Retention

The six-year financial period applies to the derived `transactions` record, not
to an unbounded copy of a payment provider's webhook. Signed Paystack and
Flutterwave bodies may contain customer email/name/phone, IP address, device
fingerprint, card BIN/last-four/bank, mobile-money phone/network details,
reusable authorization codes, metadata, redirect details, and provider
diagnostic logs. Those fields exceed DamDam's long-term tax, reconciliation,
and dispute purpose.

After signature verification and payment validation, ingestion therefore
retains an explicit allowlist:

- Paystack: event type; provider event ID; live/test domain; status; DamDam
  reference; amount and currency; payment channel; paid/created timestamps; and
  fee.
- Flutterwave: event type; provider event ID; status; DamDam and Flutterwave
  references; requested/charged amounts and currency; application/merchant
  fees; payment type; created timestamp; and merchant account ID.

Everything else is discarded rather than hashed. A hash of a payer or
instrument identifier is unnecessary for reconciliation—the opaque provider
references already provide that linkage—and would preserve avoidable
linkability. Migration `0024_retention_payment_gaps` applies the same allowlists
to existing Paystack and Flutterwave JSONB values, so the correction is not
limited to future callbacks. Provider-side records remain retrievable through
the retained references when an authorized dispute investigation genuinely
requires more detail.

Manual HTO invoice confirmations now create a successful, processor-neutral
`transactions` row in the same database commit as the order's payment-confirmed
state. Its evidence contains only the confirmation source, confirming admin ID,
and confirmation timestamp. Repeated confirmation is idempotent, including the
recovery path after a provisioning-queue outage, and a unique
`manifest_order_id` index prevents duplicate financial evidence. Migration
`0024_retention_payment_gaps` also backfills every previously confirmed HTO
order that lacks a transaction. These rows use the same `created_at`-based
six-year deletion task and deterministic `transaction_deleted` audit entry as
automated Paystack/Flutterwave payments.

---

## 10.14 Amendment — Product Reset and the Security Surface

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only. **No control above is relaxed by this amendment.** Sections
10.6 and 10.8 still require legal/GRC review before leaving draft.

`prd.md` §10 resets the product. Consequences for this document:

**Reduced data collection.** Retiring family contacts, SOS and arrival
geofencing removes third-party contact details, emergency dispatch records and
background location from the product. That is a net privacy improvement, but it
becomes real only when chunk 04 completes deletion under the approved retention
policy — not when the screens are removed. Until then, treat the retained data
as live and in scope for every control here.

**Broadened tenancy risk.** Individual memberships across many organizations
replace single-HTO scoping. Object-level authorization must be enforced in APIs,
background jobs, exports and storage access, and proven by negative cross-tenant
tests (`US-29`, AC-29.3/AC-29.4). Administrator MFA is required, and session and
token revocation must take effect immediately.

**Broadened jurisdiction.** NDPA framing above assumed Nigerian users and a
Nigerian pilot. A global product's applicable regimes depend on D2 (selling
markets) and D3 (selling entity), both open. Do not narrow or widen a compliance
claim before those are recorded.

**New sensitive material.** Real eSIM activation credentials, secrets and tokens
must never appear in code, logs, exports, fixtures or review evidence. Deliver
installation credentials only through authorized protected installation flows.
Carrier line identifiers and assigned numbers are personal/service data: mask
them in diagnostic logs and public evidence, but permit authorized My Line,
support and tenant-scoped reports to show the fields necessary for their purpose.
Use synthetic identifiers in tests and scrubbed contract fixtures; no real
customer activation credentials belong in fixtures. This distinction preserves
both data protection and the required line-management/reporting experience.

**Emergency calling is not settled by removing SOS.** Carrier emergency-calling
obligations on a real cellular line are a separate supplier and legal question
under D1 and must be answered before any market is sold.

## 10.15 Amendment — Token Clock and Refresh Concurrency

**Recorded 8 September 2026 during independent chunk 02 review (US-42).**

The shared token decoder verifies signed claims with the application's clock:
mandatory expiry, and issued-at/not-before when present. Invalid dates are
rejected, including nonfinite values; future-issued and not-yet-valid tokens
are rejected. Production's clock remains real UTC time. Controlled test clocks
therefore work both before and after real time without disabling date checks.

Consumer refresh rotation obtains a PostgreSQL row lock before checking stored
revocation and issuing a replacement. Revocation and replacement commit together,
so simultaneous uses of one refresh token cannot create two valid replacements.
The stored expiry is retained as a separate constraint from the JWT expiry.
Regression evidence includes PostgreSQL concurrency and organization verification;
these changes do not implement the broader identity/tenancy work in chunks 06/07.

---

## 10.16 Amendment — Device-Local Queues Must Be Attributable (US-30, AC-30.4)

**Recorded 9 September 2026 by build chunk 04, subchunk 04A.** No control above
is relaxed.

A shared device is a multi-tenant boundary. The offline safety queues did not
treat it as one: one SQLite file, no owner column, and an unfiltered read, so a
second person signing in on the same handset inherited the first person's queued
events and had them submitted under their own identity. Location data was
included.

Two rules follow, and they apply to any future device-local queue, cache or
outbox, not just the two being retired:

1. **Every device-local record that will later be sent to the server carries the
   account that created it**, and every read filters on it. Ownership is
   re-verified immediately before dispatch and again after the response, because
   an account can change while a request is in flight.
2. **A record whose owner cannot be established is quarantined, never adopted.**
   It is not deleted — it is a user's data — and it is never attributed to
   whoever signs in next. Deletion follows the approved retention policy.

The quarantined rows retain their original location and timestamp data and are
therefore still personal data. They are covered by the retention policy and must
be included in the deletion plan produced in subchunk 04E; chunk 04A does not
delete them.
