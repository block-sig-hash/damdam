# Chunk V02 — Outbound authorization and durable call control

**Story:** US-45.
**Depends on accepted scope:** V01 documented contract, 06, 07, 09, 10, 11.

## Outcome and scope

Implement the shared backend for mobile/browser outbound calls using V01's
verified contract. Keep live calling disabled until V03 settlement/enforcement
and the relevant commercial gates are complete. Fixtures cannot activate live
credentials or routes. Add documented schema and API contracts first.

- Model call attempts and provider legs separately; record immutable account,
  tenant/payer, seller/currency, entitlement, normalized destination, authorized
  identity, tariff version, reservation, correlation keys and expiry.
- Provide authenticated eligibility/rate preview, idempotent call authorization,
  short-lived scoped credential/grant issuance, stop and scoped history/status.
  Exact endpoint shapes must be designed/documented here, not guessed from legacy.
- Reserve maximum authorized exposure through chunk10 before any billable route.
  Provider/client wrappers enforce the approved call grant; no client-chosen rate,
  identity, payer or unrestricted direct PSTN dialing. V03 completes settlement.
- Persist initiation intent before external effects. Retry/timeout/restart must
  reconcile the original attempt before creating another leg. Separate accepted,
  ringing, answered, terminal and unknown states using actual provider semantics.
- Verify webhook signature/timestamp against raw payload; durably ingest events
  with deduplication. Handle reordered, duplicate, unknown and late provider IDs.
  Calls cannot cross tenant boundaries through endpoints, events or background jobs.
- Define logout/recovery/token expiry and membership revocation behavior; reject
  new actions and safely terminate applicable active work calls. Disabling new
  calling must not disable termination or financial recovery.

## Acceptance — AC-45.1 to AC-45.4

Prove copied/tampered/replayed credentials cannot authorize a different call;
negative ownership tests cover payer, destination, identity and provider IDs.
Use PostgreSQL concurrency tests for same-key duplicate initiation and shared
funds. Inject lost originate/bridge response, process crash, delayed webhook and
stop timeout; no duplicate PSTN leg or released unknown liability is allowed.
Upgrade representative existing data, preserve old call history and ensure
internet-only service requires no eSIM. Run API suite/lint/types, migration and
OpenAPI drift checks; vendor contract evidence must match the implemented adapter.
Any unavailable live-control proof remains separately blocked and routes disabled.

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
