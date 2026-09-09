# Chunk 26 — Harden environments, backups and operational visibility

> **Scope update — 9 September 2026:** Read [the approved calling amendment](../VOICE-EXPANSION.md). It supersedes earlier app/browser-calling deferrals and defines capability-specific release dependencies. Historical acceptance records remain valid for their reviewed scope.

**Depends on:** chunk 02, chunk 05, chunk 11.
**Plan mapping:** PR-16 part A / US-42.
**Likely starting points:** Infrastructure/scaling docs, deploy scripts, Terraform/compose, secret configuration and backup tooling.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Calling expansion requirements

Use V01-verified signaling/media requirements; configure signed callbacks, browser-origin policy and secret rotation. Observe call control and reconciliation failures separately from carrier events.

## Outcome and implementation scope

1. Update staging/production configuration for new modules with isolated databases, merchant/carrier accounts, queues and secrets.
2. Implement health/readiness, structured redacted logs, correlation IDs and actionable metrics for order age, unknown outcomes, webhook lag, usage freshness and reconciliation discrepancies.
3. Add safe worker shutdown/restart, bounded retries, alert ownership and least-privilege runtime credentials.
4. Exercise backups/restoration and migration/release rollback or roll-forward against representative staging data.
5. Make production reject mock-provider mode and unapproved live catalog/payment configuration. Prepare deployment changes without applying production infrastructure or spending.

## Acceptance and evidence

- Test missing/invalid configuration, provider outage and worker restart; verify no tokens, activation codes or sensitive payloads leak in logs.
- Perform a staging/local restore drill with recorded recovery time and reconciliation checks. Validate relevant deployment architecture compatibility.

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
