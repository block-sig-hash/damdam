# Security & Compliance Specification
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
| Payment transaction records | 6 years | Standard financial record-keeping (tax/audit), independent of NDPA |
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
   regulatory citation, not left as a draft assumption)
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
- [ ] NDPA registration/compliance filing completed if required at
      DamDam's data volume (confirm threshold)
- [ ] Incident response plan reviewed and tabletop-tested
- [ ] Data retention automation (the deletion jobs implied by
      §10.3) built and tested, not just documented
- [ ] Apple App Store and Google Play privacy label/data safety
      disclosures completed accurately (both platforms require
      declaring data collection categories at submission — this
      needs to match §10.2's classification exactly, or app review
      can be rejected/delayed)
