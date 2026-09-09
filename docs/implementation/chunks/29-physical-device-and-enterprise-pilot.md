# Chunk 29 — Run the authorized physical-device and enterprise pilot

> **Scope update — 9 September 2026:** Read [the approved calling amendment](../VOICE-EXPANSION.md). It supersedes earlier app/browser-calling deferrals and defines capability-specific release dependencies. Historical acceptance records remain valid for their reviewed scope.

**Depends on:** chunk 03, chunk 28.
**Plan mapping:** PR-17 live evidence / US-43; D1–D6.
**Likely starting points:** Approved market/device matrix, test spending authorization, live merchant/carrier approvals and pilot checklist.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Calling expansion requirements

Require V01 live route evidence for internet offers and chunk03 carrier evidence for native offers. Test Nigeria mobile/landline calls where advertised, actual caller identity, DTMF/audio and all-leg costs separately per channel.

## Outcome and implementation scope

1. Prepare an executable operator checklist and evidence record; perform only approved live purchases/calls and authorized pilot activity.
2. On supported physical iOS and Android devices, prove purchase, eSIM installation, data consumption and native call TO Nigeria with DamDam closed; inbound/caller-ID behavior where sold.
3. Record device/OS, visited network, origin/destination, assigned identity, rate version, observed charges, data usage lag, top-up and spending-limit behavior.
4. Test dual-SIM selection, DTMF/audio quality, failed installation, poor connectivity and customer recovery.
5. Run a representative enterprise administrator pilot through import, funding, partial failures, employee installation, spend reporting and offboarding. Record consented findings without leaking customer data.

## Acceptance and evidence

- Compare observed supplier charges and settlement with the ledger; close discrepancies and document call/data quality measurements against founder-approved thresholds.
- If credentials, devices, approvals or spending authorization are absent, return runnable procedures and mark live evidence blocked. Do not fabricate tests or claim launch readiness.

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
