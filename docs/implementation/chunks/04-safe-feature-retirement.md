# Chunk 04 — Retire family, safety and app-calling features safely

**Depends on:** chunk 01, chunk 02.
**Plan mapping:** PR-04 / US-30; finding 1.
**Likely starting points:** Family/check-in/SOS modules; checkInOutbox.ts and SOS queues; AuthenticatedApp.tsx; worker schedules; native permissions; release validators.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Inventory current deployed-client compatibility, stored records, pending jobs and notifications before changing behavior. Retire agreed family/SOS and associated welfare paths; resolve any remaining scope default through the decision record.
2. Disable new enrollment and retired dispatch paths, then remove UI/routes/jobs/dependencies in a compatible sequence. Old clients must receive an explicit retired/upgrade response instead of silently reporting delivery.
3. For every surviving queue or transition path, bind records to the original account, scope reads/dispatch, cancel stale work on logout and revalidate ownership before sends. Quarantine legacy rows without trustworthy ownership; never assign them to whoever logs in next.
4. Remove launch external-CLI verification and WebRTC/CallKit/VoIP-push dependencies where unused. Retain shared auth, notifications and financial history. Remove unused contacts/location/microphone permissions from native release builds.
5. Provide a dry-run retention/backfill plan for obsolete personal data; do not execute production deletion or drop historical migrations. Keep the app bootable pending the new navigation.

## Acceptance and evidence

- Exercise A queues offline → logout → B login, process restart and delayed callback; no event may be attributed to B. Run applicable repository offline/chaos tests for retained or transitioning safety code.
- Verify old jobs/clients cannot reactivate notifications, app boot/login still works, and removed features have no active permissions or dispatch references. Change obsolete release gates explicitly without disabling unrelated protection.

Also satisfy the common handoff and affected repository checks below. External prerequisites cannot be replaced by passing mocks. If only a preparatory subset can be completed, identify it and leave the remainder explicitly open.

## Working instructions for Claude Code

Implement only this chunk in the DamDam repository. Read `AGENTS.md`, `docs/README.md`, the relevant registered stories and `docs/implementation/IMPLEMENTATION-PLAN.md` first. For chunk 01, use the supplied pack before it has been copied into the repository. The supplied packet is currently at `/home/iadamu/artifacts/damdam-build-pack`; another workspace may use a different location.

The user's chosen workflow is Claude implementation followed by Codex review and, when needed, refactoring. The user has authorized this redesign and working split; older ownership tables and obsolete product freezes do not override it. Retain applicable test, security and migration safeguards.

Product boundaries: generic consumer plus enterprise/government connectivity; Telnyx preferred for data and native-dialer voice on the same eSIM, subject to verified availability. Remove family/SOS; follow the scope record for remaining welfare retirement. External verified caller ID and app VoIP are deferred. No additional carrier integration, subscriptions, AI features, SSO/SCIM or microservice rewrite unless separately approved. Entity and global payment processor remain decisions, not assumptions.

Inspect the actual current branch, local changes and dependency review records. Start from the accepted predecessor commit on a dedicated branch/worktree; preserve unrelated work. Do not code against the historical SHA blindly. If a dependency changed, explain the resulting scope adjustment. Do not silently absorb a missing predecessor's work.

Use existing modules and abstractions, numbered data-model amendments and synchronized API specs. Verify changing vendor APIs against current official documentation. Do not invent endpoints, live prices, regulatory approvals or successful test evidence.

Implement the outcome and its failure behavior. Follow strict TDD for auth and payment/idempotency and the applicable safety-transition tests. Use PostgreSQL for backend database/concurrency behavior; test mobile SQLite persistence with its actual storage. Run the affected repository-required tests, lint, types, builds and contract checks; do not disable checks or lower coverage to pass. Refactor within scope when it improves correctness or maintainability. If work needs multiple independent migrations/features, propose subchunks rather than delivering an unreviewable PR.

No production deployment, merge, store submission, outgoing vendor messages, live purchases or production data deletion is implied. Prepare reviewable code, scripts and unsent drafts; use existing authorized sandbox access appropriately. Keep secrets and eSIM activation material out of code, logs and evidence.

Finish with the handoff format in `docs/implementation/HANDOFF-TEMPLATE.md`: exact base/head SHA, clean/dirty status, changed behavior, acceptance-test evidence, commands/results, migration notes, unresolved gates and known limitations. Mark incomplete checks as incomplete. Do not mark yourself accepted or continue to the next chunk; Codex reviews first.
