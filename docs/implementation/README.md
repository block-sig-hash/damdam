# DamDam — Claude build chunks and Codex review gates

> **Scope update — 9 September 2026:** Read [the approved calling amendment](VOICE-EXPANSION.md). It supersedes earlier app/browser-calling deferrals and defines capability-specific release dependencies. Historical acceptance records remain valid for their reviewed scope.

Prepared 8 September 2026. This packet breaks the consolidated implementation plan into 30 bounded assignments. It does not implement or certify application changes.

## How to use this pack

1. Give Claude Code the repository and [chunk 01](chunks/01-scope-and-specifications.md). Each chunk file is a complete assignment with shared working rules included.
2. Claude completes that chunk on an isolated branch and returns the [handoff](HANDOFF-TEMPLATE.md). Chunk 01 copies this packet into `docs/implementation/` so subsequent sessions can read it directly.
3. Give Codex the branch/worktree or PR link, base/head SHA, and handoff. Use [REVIEW.md](REVIEW.md) as the review request.
4. Codex inspects the actual diff and surrounding behavior, runs relevant independent checks, and fixes/refactors within scope where needed. Findings cite code and explain impact. The final changed SHA is reviewed and tested.
5. Start the next dependent chunk only after Codex records acceptance. Carry fixes forward into the next branch. Acceptance does not itself merge or deploy anything.

**Chunks 01–05 have reviewed scope; consult [STATUS.md](STATUS.md).** These are review units, not day estimates. Keep one active implementation chunk by default. A large chunk may be split into lettered subchunks with explicit dependencies after its initial inspection.

This changes the earlier AGENTS.md ownership policy at the user's request: Claude builds, Codex reviews/refactors. Chunk 01 updates the repository instructions so future sessions do not revert to the old division.

## Product constraints to preserve

- A generic global eSIM and carrier-voice app, with a consumer mobile app, enterprise/government dashboard and separate internal operations.
- Telnyx is preferred for launch. Confirm same-eSIM data/native voice and saleable markets; documented VoLTE beta status and production support are an external gate.
- No family/SOS. Associated check-in/welfare removal follows the explicit scope disposition; no hidden enterprise tracking.
- External verified caller ID is deferred; a carrier-assigned number is the proposed initial identity. Do not promise +234 retention/porting.
- Outbound app/browser calling is an additional service under V01–V05; it never proves native calling. No extra launch carriers or automatic supplier failover after an unknown order outcome.
- Preserve Paystack conditionally for approved local NGN business. Global processor and legal entity are unresolved. Stripe-specific code requires a recorded selection.
- Wallet checkout means supported Apple Pay/Google Pay through a processor. Recurring subscriptions and messaging beyond the agreed offer remain separately gated.
- Retain the existing stack and useful provider boundaries. Modular code does not require a plugin marketplace or microservices.

[IMPLEMENTATION-PLAN.md](IMPLEMENTATION-PLAN.md) contains the full decisions and earlier source research. It is a snapshot of the consolidated plan supplied with this packet; later approved decisions must be recorded in the repository.

## Build sequence

The numbers are a suggested sequence. The dependency column applies with the explicit amendments and capability-specific release rules in VOICE-EXPANSION.md. Chunk 03 should start early; missing commercial answers need not block unrelated foundations. Chunk 26 can also be brought forward after its dependencies.

| Chunk | Assignment | Requires accepted chunks |
|---|---|---|
| 01 | [Reset product specifications and working rules](chunks/01-scope-and-specifications.md) | None |
| 02 | [Repair the CI baseline and screenshot harness](chunks/02-ci-baseline.md) | 01 |
| 03 | [Prove Telnyx feasibility and document the carrier contract](chunks/03-telnyx-feasibility.md) | 01 |
| 04 | [Retire family, safety and app-calling features safely](chunks/04-safe-feature-retirement.md) | 01, 02 |
| 05 | [Introduce core domain models and migration boundaries](chunks/05-core-schema.md) | 01, 02 |
| 06 | [Implement global identity and account recovery](chunks/06-identity-and-recovery.md) | 04, 05 |
| 07 | [Implement memberships, tenant isolation and administrator MFA](chunks/07-organizations-and-rbac.md) | 05, 06 |
| 08 | [Define the consumer and enterprise design system](chunks/08-design-system.md) | 01, 04 |
| 09 | [Build supported-market catalog and immutable quotes](chunks/09-catalog-and-quotes.md) | 05, 07 |
| 10 | [Build the multi-currency ledger and atomic reservations](chunks/10-ledger-and-reservations.md) | 05, 07 |
| 11 | [Build order orchestration and durable recovery](chunks/11-orders-and-durable-recovery.md) | 09, 10 |
| 12 | [Implement payment routing and modernize Paystack](chunks/12-payment-routing-and-paystack.md) | 09, 10, 11 |
| 13 | [Implement the selected global payment adapter and wallet checkout](chunks/13-global-checkout.md) | 12 |
| 14 | [Implement refunds, disputes, bank funding and receipts](chunks/14-refunds-and-reconciliation.md) | 12, 13 |
| 15 | [Implement the Telnyx eSIM, line and number lifecycle](chunks/15-telnyx-line-lifecycle.md) | 03, 05, 09, 11 |
| 16 | [Implement actual usage reconciliation and carrier charging](chunks/16-usage-and-charging.md) | 10, 15 |
| 17 | [Implement top-ups, spending controls and suspension](chunks/17-spending-controls-and-topups.md) | 14, 15, 16 |
| 18 | [Connect mobile navigation, onboarding and redemption](chunks/18-mobile-navigation-and-onboarding.md) | 06, 07, 08, 09 |
| 19 | [Build the complete consumer purchase journey](chunks/19-mobile-plans-and-checkout.md) | 12, 13, 18 |
| 20 | [Build My Line, eSIM installation and native-call guidance](chunks/20-mobile-my-line-and-installation.md) | 15, 16, 17, 19 |
| 21 | [Complete account, receipts, support and deletion](chunks/21-mobile-account-and-support.md) | 14, 18, 20 |
| 22 | [Build enterprise people, teams and validated imports](chunks/22-enterprise-people-and-imports.md) | 07, 08, 09 |
| 23 | [Build bulk orders, assignment and activation requests](chunks/23-enterprise-bulk-provisioning.md) | 11, 14, 15, 17, 22 |
| 24 | [Build enterprise funding, budgets, reports and offboarding](chunks/24-enterprise-billing-and-offboarding.md) | 14, 16, 17, 23 |
| 25 | [Build internal support and exception operations](chunks/25-internal-operations.md) | 14, 16, 23, 24 |
| 26 | [Harden environments, backups and operational visibility](chunks/26-production-environment-and-observability.md) | 02, 05, 11 |
| 27 | [Update signed builds, privacy disclosures and release automation](chunks/27-native-builds-and-release-gates.md) | 02, 04, 08, 21, 24, 26 |
| 28 | [Prove integrated flows, migrations and failure recovery](chunks/28-integration-and-failure-testing.md) | 19, 20, 21, 24, 25, 26, 27 |
| 29 | [Run the authorized physical-device and enterprise pilot](chunks/29-physical-device-and-enterprise-pilot.md) | 03, 28 |
| 30 | [Close release findings and prepare the production handoff](chunks/30-release-candidate-and-handoff.md) | 25, 27, 28, 29 |

The original PR-01–PR-17 labels remain traceability references, not a competing execution sequence. The chunk files identify their parent PR/story. Chunk 01 checks for story-ID collisions on the actual current branch.

## External gates and partial progress

| Gate | Required decision/evidence | Owner | Code can progress while open |
|---|---|---|---|
| D1 | Telnyx contract/API access, production/resale support, coverage, number/rate/cap evidence | Founder + Telnyx | Generic contracts, fixtures, recovery and platform code; no fake live carrier adapter or market approval |
| D2 | Initial selling/visited countries, calling destinations, devices and number policy | Founder/product | Eligibility engine and test-only catalog; no unverified public offers |
| D3 | Actual legal seller/entity and adviser-confirmed responsibilities | Founder + advisers | Configurable seller/money model; no hardcoded unapproved tax structure |
| D4 | Selected/approved processors, merchant accounts and settlement | Founder + processors | Payment abstractions and selected-provider sandbox; no live collection |
| D5 | Charging/refund/funding policy and economic viability | Founder/product/finance | Proposed prepaid mechanics clearly recorded; no unsupported pricing guarantees |
| D6 | Hosting/signing/secrets/devices/support and release access | Founder/release owner | Automation, local checks and procedures; no fabricated signed/device/live results |

Chunk 03 is the early feasibility exercise; chunk 15 is the production carrier implementation; chunk 29 is physical proof. Keep these separate.

If a gate blocks a chunk, Claude finishes independent preparatory work and identifies the exact missing input. Codex may accept a **named preparatory subchunk**, but must leave the unbuilt remainder and gate open. Do not declare the entire chunk complete or allow a dependent feature to use an imaginary implementation.

Passing a sandbox implementation can establish code correctness; it cannot establish merchant approval, VoLTE production support, real handset behavior or compliant selling markets.

No outbound supplier enquiries, company formation, paid pilot or production action is performed by this pack. The founder owns external decisions; Claude prepares evidence/questions and implements verified contracts.

## Five original findings: mandatory traceability

| Finding | Primary chunks | Required proof |
|---|---|---|
| Offline events can be attributed to the next signed-in account | 04; retained caches also 06/21 | Account-switch, restart and delayed-callback isolation; no unknown-owner rebinding; safe retirement |
| Existing purchase/setup screens and activation codes are disconnected | 18–20; enterprise 23 | New signup/redeem through installation and returning-user recovery in production navigation |
| Balance refresh does not measure consumption | 16/20 | Real provider reconciliation, stale readings and corrections; physical consumption in 29 |
| Accepted order with lost response can trigger a duplicate purchase | 11/15; bulk 23 | Durable original attempt, reconcile before retry/fallback, worker restart and concurrency proof |
| API test clock and iOS screenshot failures; missing real-device proof | 02/27–29 | Controlled test clock, complete screenshots, applicable CI and physical carrier/payment evidence |

Historical evidence (335 API passes, one failure, 87% coverage and 0/32 iOS screenshots) is not a current run. Chunk 02 establishes current facts. The new screenshot matrix replaces the old count.

## Required review depth

Every chunk gets an independent diff/context review. Auth and tenancy get negative authorization/recovery tests; money and orders get PostgreSQL concurrency/crash/replay checks; provider work gets documented contract checks; UI gets rendered inspection and journey tests; migrations get old-data upgrade validation.

Code review must inspect integration points and neighboring callers, not only changed files or Claude's new tests. A mock passing itself is not evidence of external compatibility. Do not add tests merely to mirror implementation or chase counts.

Relevant baseline commands, subject to the current repository scripts and CI:

- API: from `apps/api`, `pytest --cov=app`, `ruff check .`, `mypy app`; PostgreSQL, migration and OpenAPI drift checks as configured.
- Mobile: from `apps/mobile`, `npm test -- --runInBand`, `npm run lint`, `npm run type-check`; native build/screenshots for affected native/UI work.
- Dashboard: from `apps/dashboard`, `npm test`, `npm run lint`, `npm run type-check`, `npm run build`.
- Release: the amended signoff validator, restore/migration drills and physical test matrix where applicable.

Run the affected required checks per chunk. Run the complete integrated matrix in chunk 28 and after material release fixes; do not rerun unrelated suites endlessly after checks pass.

## Review records and acceptance

Use [STATUS.md](STATUS.md) to track progress, without calling a chunk accepted before independent review. Store sanitized build handoffs in `handoffs/NN.md` and review records in `reviews/NN.md` inside the repository packet.

Statuses: **NOT_STARTED**, **IN_PROGRESS**, **READY_FOR_REVIEW**, **CHANGES_REQUIRED**, **ACCEPTED**, **EXTERNAL_BLOCKED**. A review record names the tested head SHA and any independent external gates; changing code after that SHA invalidates affected evidence.

P0/P1 defects and material P2 correctness, authorization, financial, data-loss or acceptance gaps block acceptance. Unverified required tests also remain open. Nonblocking maintenance suggestions may be explicitly deferred with an owner; never relabel unfinished required behavior as optional.

A screenshot/native test that needs unavailable hardware remains pending; split out its evidence subchunk if necessary rather than silently dropping it. A software subchunk can be accepted while the final production gate remains open.

## Copyable first message to Claude

```text
Implement DamDam chunk 01 only from the supplied damdam-build-pack.
The pack is at /home/iadamu/artifacts/damdam-build-pack on this workspace.
Read chunks/01-scope-and-specifications.md and follow its full instructions.
Copy the pack into the repo's docs/implementation as part of the chunk.
My chosen workflow is Claude builds and Codex reviews/refactors before
the next chunk. Update conflicting older agent ownership instructions.
Return the required handoff. Do not implement chunk 02 yet.
```

For later sessions:

```text
Implement DamDam chunk NN only from docs/implementation/chunks/.
Read its full assignment, AGENTS.md and the accepted dependency reviews.
Start from the latest accepted code, preserve unrelated changes,
run required checks and return docs/implementation/HANDOFF-TEMPLATE.md.
Do not mark your own work accepted or start another chunk.
```

## Calling expansion — current execution overlay

Read [VOICE-EXPANSION.md](VOICE-EXPANSION.md) before using any numbered assignment.
It adds V01–V05 without renumbering 01–30, defines amended dependencies and phased
release gates, and records the approved concurrent work. Start the new track with
[handoffs/V01-start.md](handoffs/V01-start.md). The chunk 01 copyable message above
is retained as the original pack bootstrap, not today's next assignment.
