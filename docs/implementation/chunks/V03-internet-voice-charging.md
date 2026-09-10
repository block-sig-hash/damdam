# Chunk V03 — Internet-call metering, settlement and spend enforcement

**Story:** US-46.
**Depends on accepted scope:** V02, 10, 14.

## Outcome and scope

Complete internet-voice charging through the existing shared ledger; do not
create a second mobile/browser wallet or use client elapsed time as billing truth.

- Apply immutable customer tariff versions, exact decimal amounts/currency and
  documented rounding/start/minimum/billing increments to authoritative usage.
  Correlate provider legs to one customer attempt; store actual supplier costs
  separately and reconcile billing/CDRs with event-derived provisional state.
- Atomically reserve/extend/release exposure and settle once. Account for failed,
  busy, unanswered and partially connected calls according to documented charges.
  Disputes/corrections create compensating entries, never edit posted history.
- Enforce bounded maximum cost/duration using V01's proven server/provider method;
  renew reservations only when funds and budgets permit. Durable deadlines survive
  worker restarts; client closure never controls payment or termination.
- Delay release for unknown provider outcomes. Reconcile orphaned legs, missing
  terminal events, late final costs and supplier adjustments into an exception
  queue. State how unmatched charges are resolved and how negative exposure is
  handled without silently using another currency or payer.
- Integrate with carrier ledger/control interfaces from 16/17 when accepted.
  Before that, test shared reservation semantics but explicitly keep simultaneous
  unrestricted carrier/internet spending disabled. A delayed CDR is not a cap.

## Acceptance — AC-46.1 to AC-46.4

Prove simultaneous app/browser attempts cannot overspend; test replay, events
out of order, rate changes mid-call, multi-leg duration, missing CDR, currency
mismatch, worker crash, provider outage, tab exit and expired reservation.
A fake-client-only hangup test cannot prove a provider termination bound. Include
live evidence when authorized or keep the live route gate open. Demonstrate
settlement idempotency and convergence with an independent expected-cost ledger
fixture, not just implementation-mirroring assertions. API tests/lint/types,
PostgreSQL concurrency, migrations and OpenAPI checks apply to changed scope.

## Working and handoff rules

Read AGENTS.md, the docs index, [the calling amendment](../VOICE-EXPANSION.md),
PRD §11, DECISIONS.md and the accepted dependency reviews. Inspect current
branches/worktrees; use an isolated branch from accepted code and preserve
unrelated work. Do not implement missing prerequisites. Claude implements;
Codex independently reviews/refactors. Do not mark your own work accepted.

Use internal provider/service boundaries, numbered data-model amendments and
synchronized API contracts. Never restore chunk 04 wholesale. Keep historical
financial data and the quantity-one order-item invariant. Follow strict TDD for
authorization, idempotency, money and concurrency; use PostgreSQL for backend
behavior. Run affected repository checks and meaningful failure tests. Report
unrun checks and external limitations explicitly; a mock is not live evidence.

No vendor message, paid call/purchase, deployment, merge, store submission or
production deletion is authorized by this assignment. Prepare unsent enquiries;
use existing authorized sandbox access only. Keep credentials out of logs/docs.
Return [HANDOFF-TEMPLATE.md](../HANDOFF-TEMPLATE.md) at `handoffs/VNN.md` (use this
chunk's ID), record exact base/head SHAs and status, and stop for Codex review.
