# DamDam — Documentation Index

DamDam is a mobile connectivity platform for Nigerian travelers,
combining prepaid eSIM data, verified Nigerian caller ID, and
group safety features — launching with Hajj & Umrah pilgrims as
the initial wedge market, expanding to general Nigerian travelers
and enterprise/government duty-of-care contracts.

This folder is the single source of truth for product, technical,
security, and infrastructure decisions. Read in this order:

| # | Document | Purpose |
|---|---|---|
| 1 | [`prd.md`](./prd.md) | Product Requirements — scope, user types, user stories, acceptance criteria |
| 2 | [`data-model.md`](./data-model.md) | Database schema — every table, field, relationship |
| 3 | [`api-spec.md`](./api-spec.md) | API contract — every endpoint, request/response shape |
| 4 | [`frontend-mobile.md`](./frontend-mobile.md) | Mobile app (iOS + Android) — screens, flows, states |
| 5 | [`frontend-dashboard.md`](./frontend-dashboard.md) | HTO & Admin web dashboard — screens, flows, states |
| 6 | [`security.md`](./security.md) | Security & compliance — NDPA, data retention, encryption |
| 7 | [`infrastructure.md`](./infrastructure.md) | Hosting, CI/CD, monitoring, backups, cost |
| 8 | [`scaling-infrastructure.md`](./scaling-infrastructure.md) | **Forward-looking** — multi-region architecture, global payments, AI-tooling split for post-MVP scale |
| 9 | [`corporate-structure.md`](./corporate-structure.md) | Entity structure (UAE parent + Nigeria OpCo), payment rail allocation, pre-launch legal action items |
| 10 | [`testing-qa.md`](./testing-qa.md) | TDD policy, coverage targets mapped to acceptance criteria, device matrix, offline/chaos testing for check-in & SOS |
| 11 | [`design-system.md`](./design-system.md) | Mobile app design tokens/patterns; produced and required for all Codex-implemented screens |

## Status

All documents are **v0.1 DRAFT** as of July 2026. Security spec
sections 10.6 and 10.8 specifically require legal/GRC review
before this moves from draft to final — flagged inline.

## Change log discipline

Any change to a spec that affects another spec (e.g., a data
model change that requires an API amendment) must be captured
as a numbered amendment within the affected document, not a
silent edit — see `data-model.md` §6.4 and §6.5 for the pattern
to follow.
