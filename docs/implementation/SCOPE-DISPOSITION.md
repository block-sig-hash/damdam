# Legacy scope disposition

Opened by [chunk 01](chunks/01-scope-and-specifications.md) on 8 September 2026.

The active specs were written for a Hajj-pilgrim product with family contacts,
offline SOS, verified Nigerian caller ID, app-based WebRTC calling and a
tour-operator (HTO) dashboard. The product reset replaces that with a generic
global consumer plus enterprise/government connectivity product.

Those references have **not** been deleted. Chunk 01 is a documentation reset,
not a rewrite, and deleting decision history would destroy the traceability the
repository's amendment convention exists to preserve. Instead every legacy
concept is classified here, and each affected spec carries an amendment pointing
at this file.

## Classification vocabulary

| Class | Meaning |
|---|---|
| **RETIRED** | The feature leaves the product. Spec text describing it stays as a record of what is being removed; a named chunk owns the removal. |
| **GENERALIZED** | The underlying concept survives under a new, non-Hajj name. Spec text is superseded by the new contract, not deleted. |
| **DEFERRED** | Out of launch scope, retained as a future commercial question. Not a launch disqualifier. |
| **HISTORICAL** | A dated amendment or decision record. Stays permanently, read as "what was true then", never as current scope. |

## Concept dispositions

| Legacy concept | Class | Replacement | Removal owned by |
|---|---|---|---|
| Hajj / Umrah / pilgrim / NAHCON framing | GENERALIZED | Generic consumer traveler; no pilgrimage, departure-date or Saudi-destination requirement | 04 (behavior), 18–21 (UI), 09 (catalog) |
| Family contacts (`family_contacts`, nomination, WhatsApp notification) | RETIRED | none | 04 |
| Offline SOS (`sos_alerts`, `sos_notifications`, dispatch, HTO alerting) | RETIRED | none | 04 |
| Check-in / welfare workflow (`check_ins`, `check_in_notifications`, roster status) | **PROPOSED RETIREMENT**, see product-default note below | none | 04 |
| Arrival geofencing (`destination_geofences`) | RETIRED | none | 04 |
| Verified Nigerian caller ID (`verified_cli`, `caller_id_verifications`) | DEFERRED | Carrier-assigned number as outbound identity | 04 (launch dependency), 15 (number lifecycle) |
| +234 retention / porting | DEFERRED | New assigned number; **no retention promise** | D2 decision, then 15 |
| App/WebRTC calling (`voice_credentials`, `voiceGateway.ts`, `callKit.ts`) | Legacy implementation retired; outbound service newly AUTHORIZED | Fresh app/browser integration alongside carrier calling; inbound remains deferred | V01–V05 under [calling amendment](VOICE-EXPANSION.md); 04 acceptance preserved |
| HTO operator / licence / manifests | GENERALIZED | Organization, membership, people import, bulk allocation | 07, 22, 23, 24 |
| Family Contact user type | RETIRED | none | 04, plus `prd.md` §10 user-type replacement |
| NGN-only money and admin-managed Naira pricing | GENERALIZED | Multi-currency money with explicit ISO currency and tariff versions | 05, 09, 10 |
| Pilot feature freeze and `v0.1.0-rc.1` gate semantics | HISTORICAL | The chunk/review workflow in [README.md](README.md) | superseded by chunk 01; release gates re-cut in 27 |
| UAE parent + Nigeria OpCo recommendation | HISTORICAL | Undecided — D3 | D3 decision, then 30 |
| Three-way eSIM aggregator failover (Monty / eSIM Access / 1GLOBAL) | RETIRED as launch behavior | Telnyx only; extension points preserved, **no automatic failover after an unknown outcome** | 11, 15 |

### The check-in disposition is a proposed default, not a decision

Removing family contacts and SOS is the user's explicit decision. Removing the
**remaining check-in / welfare workflow** is recorded in
[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) §1 as a *recommended scope
interpretation*. It is carried in [DECISIONS.md](DECISIONS.md) as a proposed
default owned by founder/product. Confirm the final disposition before irreversible
removal of remaining welfare data or a launch promise about that service. Reversible
inventory, isolation and migration preparation may proceed, as may the already
authorized family/SOS removal. Do not quietly retain welfare tracking in the
enterprise dashboard. Record a founder decision already supplied in the session
without asking for it again.

### SOS removal is not emergency-calling removal

Retiring DamDam's in-app SOS says nothing about carrier emergency-calling
obligations on a real cellular line. That is a separate supplier and legal
question under D1, and it must be answered before any market is sold.

## Per-spec reference inventory

Counts are case-insensitive line matches on the base commit `6790c74`. They
measure how much text each spec carries about each retired concept — they are a
work-sizing input for later chunks, not a defect list.

| Spec | Hajj/pilgrim | Family | SOS | Check-in | WebRTC | Verified CLI | HTO | Dominant class |
|---|---|---|---|---|---|---|---|---|
| `prd.md` | 82 | 33 | 32 | 25 | 4 | 4 | 36 | GENERALIZED + RETIRED |
| `data-model.md` | 84 | 32 | 11 | 24 | 1 | 6 | 36 | HISTORICAL (amendments) + RETIRED (tables) |
| `api-spec.md` | 63 | 16 | 14 | 13 | 1 | 6 | 74 | GENERALIZED + RETIRED |
| `frontend-dashboard.md` | 33 | 10 | 18 | 3 | 0 | 0 | 29 | GENERALIZED |
| `frontend-mobile.md` | 16 | 14 | 18 | 5 | 0 | 5 | 6 | RETIRED |
| `testing-qa.md` | 13 | 1 | 18 | 15 | 3 | 1 | 9 | RETIRED (gates) + HISTORICAL |
| `security.md` | 17 | 4 | 11 | 8 | 0 | 1 | 10 | GENERALIZED |
| `i18n-scoping.md` | 9 | 13 | 30 | 10 | 0 | 0 | 7 | HISTORICAL |
| `infrastructure.md` | 10 | 0 | 6 | 5 | 0 | 0 | 8 | GENERALIZED |
| `pre-pilot-checklist.md` | 4 | 3 | 12 | 8 | 0 | 4 | 10 | HISTORICAL (superseded gates) |
| `design-system.md` | 3 | 4 | 13 | 0 | 0 | 0 | 3 | RETIRED |
| `scaling-infrastructure.md` | 5 | 0 | 1 | 0 | 2 | 0 | 0 | HISTORICAL |
| `corporate-structure.md` | 4 | 0 | 0 | 0 | 0 | 0 | 1 | HISTORICAL (D3) |
| `localization.md` | 2 | 4 | 5 | 2 | 0 | 0 | 1 | RETIRED (string scope) |
| `verified-cli-scoping.md` | 3 | 0 | 2 | 0 | 4 | 6 | 0 | DEFERRED (whole document) |

Reproduce with:

```bash
cd docs
for f in *.md; do
  printf '%-28s %3s %3s %3s %3s %3s %3s %3s\n' "$f" \
    "$(grep -ciE 'hajj|umrah|pilgrim|nahcon' "$f")" \
    "$(grep -ciE '\bfamily|family_contact' "$f")" \
    "$(grep -ciE '\bsos\b' "$f")" \
    "$(grep -ciE 'check-?in' "$f")" \
    "$(grep -ciE 'webrtc' "$f")" \
    "$(grep -ciE 'verified_cli|verified cli|verified caller' "$f")" \
    "$(grep -ciE '\bHTO\b' "$f")"
done
```

## Whole documents whose status changed

| Document | New status |
|---|---|
| `verified-cli-scoping.md` | **DEFERRED in full.** Retained as the record of a deferred commercial question. Not a launch input. Its §5 MVP scope is not a commitment. |
| `pre-pilot-checklist.md` | **SUPERSEDED as a gate, retained as history.** Its Hajj-pilot framing, feature freeze and SOS/CLI/WebRTC items are not current release criteria. Chunk 27 re-cuts the real gates. |
| `i18n-scoping.md` | **HISTORICAL scoping**, except its §10 amendment describing shipped English/French architecture, which stays current. Safety/SOS string scope is retired with the feature. |
| `corporate-structure.md` | **HISTORICAL recommendation.** The UAE-parent structure is not a decision; D3 is open. |
| `scaling-infrastructure.md` | **Forward-looking, unchanged in status.** Its multi-region and microservice content stays explicitly out of launch scope. |

## What chunk 01 deliberately did not do

- It did **not** delete legacy spec sections. Later chunks retire behavior and
  then amend the specs that describe it, so the retirement is reviewable.
- It did **not** change `scripts/validate-release-signoff.sh`. That script still
  requires "Offline check-in survival" and "Offline SOS survival" rows in every
  release signoff. Removing them is release automation and belongs to
  **chunk 27**; it is recorded in [STATUS.md](STATUS.md) as a known
  compatibility constraint between the reset and the legacy validator. Until
  chunk 27 updates template and validator together, the workflow still expects
  the legacy rows. Current server-side merge enforcement is unverified; see
  [BASELINE.md](BASELINE.md). Never fabricate retired-feature evidence to pass it.
- It did **not** touch application code, migrations or CI configuration.
