# Chunk 15 — Implement the Telnyx eSIM, line and number lifecycle

> **Scope update — 9 September 2026:** Read [the approved calling amendment](../VOICE-EXPANSION.md). It supersedes earlier app/browser-calling deferrals and defines capability-specific release dependencies. Historical acceptance records remain valid for their reviewed scope.

**Depends on:** chunk 03, chunk 05, chunk 09, chunk 11.
**Plan mapping:** PR-09 / US-35; finding 4.
**Likely starting points:** Approved Telnyx contract/probe evidence; existing provider abstractions; connectivity/order specifications.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Calling expansion requirements

Keep carrier and internet adapter capabilities separate. Common assigned-number reuse requires provider evidence; internet-only callers do not require a carrier line.

## Outcome and implementation scope

1. Implement the real documented Telnyx adapter behind internal connectivity interfaces for profile issuance/lookup, voice enablement, assigned-number retrieval and supported activation/lifecycle operations.
2. Map provider statuses to separate profile, line, number, installation and connectivity states without claiming activation from QR delivery.
3. Apply persisted attempt identity and unknown-outcome reconciliation to all billable or irreversible operations. No silent legacy-vendor fallback.
4. Protect eSIM installation credentials and provider identifiers in storage, logs, APIs and access control. Use short-lived authorized delivery where appropriate.
5. Expose capabilities for later top-up, suspension and usage work. If beta API contracts/access are unavailable, do not invent endpoints or label a fake adapter production-ready.

## Acceptance and evidence

- Run contract tests for actual documented payloads/errors and missing/changed fields; repeat the initial accepted-but-response-lost test against the adapter boundary.
- With authorized test access, verify one profile and assigned line/number correlate correctly. Record live evidence separately from fixture tests; production service capability remains subject to D1.

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
