# Corporate Structure

> **Current scope:** the September 2026 reset in §13.5 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

# DamDam — Version 0.1

This document is the source of truth for DamDam's entity structure
and payment-rail allocation, referenced from `security.md` §10.1
and `scaling-infrastructure.md` §12.6. It is a legal/business
decision record, not a product requirement — treat it the same way
as `security.md`: a working draft for legal/tax counsel to tighten,
not a finished artifact.

---

## 13.1 Recommendation Summary

**Single UAE entity as parent/IP holder now.** Revisit multi-entity
treasury structures (e.g., a separate Holdco layered above the UAE
entity, or additional jurisdictions for tax optimization) only once
revenue scales past the roughly **$5–50M range**. Below that
threshold, added entity complexity costs more in legal/accounting
overhead than it saves — this is a deliberate "don't over-engineer
the corporate structure before there's real revenue to protect"
decision, mirroring the same build-only-what's-needed principle
applied to infrastructure in `scaling-infrastructure.md` §12.1.

---

## 13.2 Nigeria Entity, Structure, and Payments

### Why a Nigeria entity is needed at all

**Not needed for app store distribution** — per `prd.md` §7, the
app itself doesn't require a Nigerian entity to publish on either
the App Store or Play Store; the UAE parent can hold both developer
accounts directly.

**Effectively required for payment settlement.** Paystack requires
a Nigerian bank account and BVN (Bank Verification Number) even at
its lightest account tier — there is no path to accepting Naira
bank transfer, USSD, or local card payments (the core checkout
flow specified in `api-spec.md` §7.3 and `prd.md` US-09) without a
Nigeria-resident entity or individual holding the merchant
relationship.

**Likely advisable for regulatory footing.** Nigeria's telecom and
data-protection regulators — the NCC (Nigerian Communications
Commission) and NDPC (Nigeria Data Protection Commission,
established under the NDPA 2023 referenced throughout
`security.md`) — generally expect a Nigerian legal presence for
consumer-facing telecom-adjacent services and data controller
accountability, even where the actual eSIM/voice infrastructure is
provided by foreign partners (Twilio, Airalo/eSIM Access, per
`prd.md` §5.4–5.5).

### Recommended structure

**A wholly-owned Nigerian subsidiary of the UAE parent** — not a
distributor or reseller relationship. This distinction matters:

- **UAE parent** holds the brand, IP, core technology, and the app
  store developer accounts (both iOS and Android per `prd.md`
  §1/§6).
- **Nigeria OpCo** (wholly-owned subsidiary) handles:
  - Local KYC and consumer contract relationships (the actual
    Terms of Service the pilgrim/traveler agrees to at signup,
    per `security.md` §10.10)
  - The Paystack merchant relationship and all Naira collection
  - NCC/NDPC regulatory registration and compliance filings

A subsidiary (rather than a reseller) keeps IP and brand value
concentrated in the UAE parent — relevant if DamDam later raises
outside capital, since investors generally prefer a clean parent-
subsidiary cap table over a distributor arrangement with a
separate Nigerian rights-holder.

### Paystack account tier

**Upgrade to a full Registered Business account, not the ₦2M-capped
Starter tier.** Given expected Hajj-season volume — even the pilot
scenario in the margin model runs 1,500 pilgrims at a Standard-tier
price point, well past what a capped starter account can process —
the Nigeria OpCo should register as a full Registered Business from
the outset rather than starting on a consumer-grade tier and
migrating under time pressure right before the first real HTO
manifest orders land.

### Payment rail allocation

| Revenue source | Rail | Entity |
|---|---|---|
| Naira collection (Hajj packages, general traveler, Nigeria-based enterprise) | Paystack (primary), Flutterwave (automatic fallback on Paystack outage — see `data-model.md` §6.7, not a second collection channel requiring separate merchant-of-record consideration) | Nigeria OpCo |
| UAE-side or international-card revenue (future non-Nigeria corridors, per `scaling-infrastructure.md` §12.6) | Stripe or similar | UAE parent (or a separate entity, TBD once that revenue is real — see §13.3) |

This mirrors the "home-region" payment logic already specified in
`scaling-infrastructure.md` §12.6 — Paystack stays the Nigeria-
specific rail, a second processor is introduced only once there's
real international-card revenue to justify it, not speculatively
now.

---

## 13.3 What This Document Deliberately Does Not Decide

- **Exact UAE entity type** (mainland vs. free zone, and which free
  zone if applicable) — a jurisdiction-specific decision for UAE
  corporate counsel, not resolved here.
- **Tax treatment of the Nigeria OpCo → UAE parent relationship**
  (transfer pricing, intercompany service agreements, withholding
  tax on any intercompany payments) — flagged for accountant/tax
  counsel review, not assumed here.
- **The specific entity that becomes Stripe's seller-of-record**
  once non-Nigeria revenue is real (§13.2 above) — left open
  pending real transaction volume, consistent with the "revisit at
  $5–50M" principle in §13.1.
- **Founder equity/cap table structure within the UAE parent** —
  out of scope for this document entirely; this covers operating
  entity structure, not ownership structure.

---

## 13.4 Pre-Launch Action Items

- [ ] Incorporate UAE parent entity, register both app store
      developer accounts under it
- [ ] Incorporate Nigeria OpCo as a wholly-owned subsidiary
- [ ] Register Nigeria OpCo for a Paystack Registered Business
      account (not Starter tier)
- [ ] File NCC/NDPC registrations as applicable for the Nigeria
      OpCo (confirm exact requirements with Nigerian regulatory
      counsel — this document assumes registration is advisable,
      not confirms the specific filing requirements)
- [ ] Draft the intercompany agreement between UAE parent and
      Nigeria OpCo (IP licensing, service fees, or equivalent) with
      tax counsel before the Nigeria OpCo begins processing real
      revenue

---

## 13.5 Amendment — The Entity Recommendation Is Not a Decision

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only.

`prd.md` §10 resets the product to a global consumer and enterprise offering,
which changes the inputs to every structuring question above.

**The UAE parent + Nigeria OpCo structure recommended in this document is
reclassified as a historical recommendation, not a decision.** It was not
selected. US LLC (via Stripe Atlas), a UK operating company and Isle of Man were
all evaluated in the 7–8 September planning conversation and **none was
selected** either. Nigerian treatment must be assessed alongside whichever is
chosen.

This is decision **D3**, owned by the founder with cross-border tax and legal
advisers, and it is **OPEN** — see
[`implementation/DECISIONS.md`](./implementation/DECISIONS.md). It blocks
merchant onboarding (D4), the seller identity shown on receipts, and tax
configuration.

Engineering constraint until D3 closes: the selling legal entity and its tax
treatment are **data**, carried on quotes, orders and receipts. No chunk may
hardcode an entity, a jurisdiction or a tax structure. The payment-provider
enquiry retained at
[`implementation/damdam-payment-provider-enquiry.md`](./implementation/damdam-payment-provider-enquiry.md)
remains an **unsent draft** and must be revised for the chosen candidate entity
before any authorized outreach.
