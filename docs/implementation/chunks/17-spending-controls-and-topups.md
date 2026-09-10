# Chunk 17 — Implement top-ups, spending controls and suspension

> **Scope update — 9 September 2026:** Read [the approved calling amendment](../VOICE-EXPANSION.md). It supersedes earlier app/browser-calling deferrals and defines capability-specific release dependencies. Historical acceptance records remain valid for their reviewed scope.

**Depends on:** chunk 14, chunk 15, chunk 16.
**Plan mapping:** PR-10 part B / US-36.
**Likely starting points:** Supplier control evidence; enterprise prepaid policy; ledger and line lifecycle contracts.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Calling expansion requirements

Before enabling shared carrier/internet credit, prove independently bounded carrier exposure while the app is closed. A UI balance or delayed CDR is insufficient; preserve safe controls while other modes are disabled.

## Outcome and implementation scope

1. Implement supported line reuse/top-ups with idempotent payment/reservation/provisioning and recoverable partial states.
2. Apply plan expiry, low-balance notices and organization budgets with supplier enforcement where promised.
3. Distinguish requested, pending, confirmed and failed suspension/resumption. Show app estimates as estimates when usage is delayed.
4. Use documented provider hard limits or a separately approved bounded-exposure product policy; do not claim delayed app accounting stops native calls.
5. Handle concurrent calls/top-ups, late usage after suspension and reinstatement without giving away allowance or losing paid credit.

## Acceptance and evidence

- Simulate and, where authorized, observe exhaustion while DamDam is closed, delayed CDRs and supplier-control failures.
- Test duplicate top-ups, unsupported profile reuse, expiry boundaries and suspend/resume races. Missing enforceable prepaid controls keep the relevant offer gated.

Also satisfy the common handoff and affected repository checks below. External prerequisites cannot be replaced by passing mocks. If only a preparatory subset can be completed, identify it and leave the remainder explicitly open.

## Working instructions for Claude Code

Implement only this chunk in the DamDam repository. Read `AGENTS.md`, `docs/README.md`, the relevant registered stories and `docs/implementation/IMPLEMENTATION-PLAN.md` first. For chunk 01, use the supplied pack before it has been copied into the repository. The supplied packet is currently at `/home/iadamu/artifacts/damdam-build-pack`; another workspace may use a different location.

The user's chosen workflow is Claude implementation followed by Codex review and, when needed, refactoring. The user has authorized this redesign and working split; older ownership tables and obsolete product freezes do not override it. Retain applicable test, security and migration safeguards.

Product boundaries: generic consumer plus enterprise/government connectivity; Telnyx preferred for data and native-dialer voice on the same eSIM, subject to verified availability. Remove family/SOS; follow the scope record for remaining welfare retirement. External verified caller ID and incoming app/browser ringing remain deferred. Outbound internet calling is assigned to V01–V05; apply the calling amendment to this chunk. No additional carrier integration, subscriptions, AI features, SSO/SCIM or microservice rewrite unless separately approved. Entity and global payment processor remain decisions, not assumptions.

Inspect the actual current branch, local changes and dependency review records. Start from the accepted predecessor commit on a dedicated branch/worktree; preserve unrelated work. Do not code against the historical SHA blindly. If a dependency changed, explain the resulting scope adjustment. Do not silently absorb a missing predecessor's work.

Use existing modules and abstractions, numbered data-model amendments and synchronized API specs. Verify changing vendor APIs against current official documentation. Do not invent endpoints, live prices, regulatory approvals or successful test evidence.

Implement the outcome and its failure behavior. Follow strict TDD for auth and payment/idempotency and the applicable safety-transition tests. Use PostgreSQL for backend database/concurrency behavior; test mobile SQLite persistence with its actual storage. Run the affected repository-required tests, lint, types, builds and contract checks; do not disable checks or lower coverage to pass. Refactor within scope when it improves correctness or maintainability. If work needs multiple independent migrations/features, propose subchunks rather than delivering an unreviewable PR.

No production deployment, merge, store submission, outgoing vendor messages, live purchases or production data deletion is implied. Prepare reviewable code, scripts and unsent drafts; use existing authorized sandbox access appropriately. Keep secrets and eSIM activation material out of code, logs and evidence.

Finish with the handoff format in `docs/implementation/HANDOFF-TEMPLATE.md`: exact base/head SHA, clean/dirty status, changed behavior, acceptance-test evidence, commands/results, migration notes, unresolved gates and known limitations. Mark incomplete checks as incomplete. Do not mark yourself accepted or continue to the next chunk; Codex reviews first.
