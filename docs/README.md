# DamDam — Documentation Index

DamDam is a global eSIM and carrier-voice platform for individual consumers and
for enterprise and government organizations. A customer buys connectivity in
DamDam, installs an eSIM, and uses their phone's normal dialer and mobile data —
one carrier-enabled profile carries both. Telnyx is the preferred launch
supplier, subject to verified availability.

This folder is the single source of truth for product, technical, security and
infrastructure decisions.

> **Read this first.** The product was reset on 8 September 2026 from a
> Hajj-pilgrim product to the description above. The specs below have **not**
> been rewritten yet — they still contain Hajj, family-contact, SOS, check-in,
> verified-caller-ID, WebRTC-calling and HTO material.
> [`prd.md` §10](./prd.md) is the reset product definition and governs where it
> disagrees with anything else, and
> [`implementation/SCOPE-DISPOSITION.md`](./implementation/SCOPE-DISPOSITION.md)
> says which legacy references are retired, generalized, deferred or purely
> historical. Check it before acting on any spec text about those topics.

## Current build

| # | Document | Purpose |
|---|---|---|
| — | [`implementation/README.md`](./implementation/README.md) | **Start here to build.** The 30-chunk sequence, dependencies, review gates and handoff format |
| — | [`implementation/BASELINE.md`](./implementation/BASELINE.md) | What is actually passing and failing right now, with run IDs — observed, not historical |
| — | [`implementation/DECISIONS.md`](./implementation/DECISIONS.md) | D1–D6 external gates, all open, with owners and required evidence |
| — | [`implementation/STORY-MAP.md`](./implementation/STORY-MAP.md) | Chunk → story routing and the five original findings' traceability |
| — | [`implementation/SCOPE-DISPOSITION.md`](./implementation/SCOPE-DISPOSITION.md) | Which legacy concepts are retired, generalized, deferred or historical |
| — | [`implementation/MODULE-OWNERSHIP.md`](./implementation/MODULE-OWNERSHIP.md) | Module boundaries, existing-code mapping and journey routing |
| — | [`implementation/IMPLEMENTATION-PLAN.md`](./implementation/IMPLEMENTATION-PLAN.md) | The consolidated plan the chunks are cut from |
| — | [`implementation/telnyx/`](./implementation/telnyx/) | Carrier feasibility evidence for D1/D2 — capability matrix, API contracts, go/no-go and the **unsent** supplier enquiry |

## Specifications

Recommended reading order:

| # | Document | Purpose | Reset status |
|---|---|---|---|
| 1 | [`prd.md`](./prd.md) | Product requirements, user types, stories and acceptance criteria | §10 is the reset; §§1–9 are historical |
| 2 | [`data-model.md`](./data-model.md) | Database schema — every table, field, relationship | §6.42 amendment; schema reset begins in chunk 05 |
| 3 | [`api-spec.md`](./api-spec.md) | API contract — every endpoint and shape (`api-spec.yaml` is the generated OpenAPI CI compares against) | §7.26 amendment |
| 4 | [`frontend-mobile.md`](./frontend-mobile.md) | Mobile app (iOS + Android) — screens, flows, states | §8.9 amendment; rebuilt in chunks 18–21 |
| 5 | [`frontend-dashboard.md`](./frontend-dashboard.md) | Enterprise/government web dashboard | §9.9 amendment; rebuilt in chunks 22–24 |
| 6 | [`security.md`](./security.md) | Security and compliance — data protection, retention, encryption | §10.14 amendment; no control relaxed |
| 7 | [`infrastructure.md`](./infrastructure.md) | Hosting, CI/CD, monitoring, backups, cost | §11.15 amendment carries the current baseline |
| 8 | [`scaling-infrastructure.md`](./scaling-infrastructure.md) | **Forward-looking** — multi-region, global payments, post-MVP scale | §12.11 amendment; still out of launch scope |
| 9 | [`corporate-structure.md`](./corporate-structure.md) | Entity structure and payment rail allocation | §13.5 amendment — the recommendation is **not** a decision (D3) |
| 10 | [`testing-qa.md`](./testing-qa.md) | TDD policy, coverage mapped to acceptance criteria, device matrix | §14.13 amendment revises the strict-TDD categories |
| 11 | [`design-system.md`](./design-system.md) | Design tokens and component patterns | §15.3 amendment; revised in chunk 08 |
| 12 | [`localization.md`](./localization.md) | English/French process — keys, locale, notifications, review, screenshots | §9 amendment; process retained, content re-scoped |

## Reference and historical

| Document | Status |
|---|---|
| [`pre-pilot-checklist.md`](./pre-pilot-checklist.md) | **Superseded as a gate**, retained as history. Its pilot feature freeze is lifted; see its closing amendment |
| [`i18n-scoping.md`](./i18n-scoping.md) | §10 (shipped English/French architecture) is current; §§1–9 are historical scoping |
| [`verified-cli-scoping.md`](./verified-cli-scoping.md) | **Deferred in full.** Retained as the record of a deferred commercial question |
| [`release-signoffs/`](./release-signoffs/) | Release signoff artifacts and `TEMPLATE.md`. The template and its validator still demand retired SOS/check-in evidence — chunk 27 re-cuts them |
| [`implementation/damdam-product-shape.md`](./implementation/damdam-product-shape.md) | Earlier product discussion, superseded by the implementation plan |
| [`implementation/damdam-payment-provider-enquiry.md`](./implementation/damdam-payment-provider-enquiry.md) | **Unsent draft.** Revise for the D3 entity before any authorized outreach |

## Status

Specs 1–12 are **v0.1 DRAFT**, written July 2026 for the previous product, and
carry the 8 September 2026 reset amendments listed above. `security.md` §10.6
and §10.8 still require legal/GRC review before leaving draft.

No external decision is closed. D1–D6 are all open. Nothing in these documents
certifies production readiness, merchant approval, carrier capability or device
behavior.

## Change log discipline

Any change to a spec that affects another spec must be captured as a **numbered
amendment** in the affected document, not a silent edit — see `data-model.md`
§6.4 and §6.5 for the pattern. Removing a feature is a change like any other:
amend the specs that describe it rather than deleting the record.
