# Chunk 07 — Implement memberships, tenant isolation and administrator MFA

**Depends on:** chunk 05, chunk 06.
**Plan mapping:** PR-03 part B / US-29.
**Likely starting points:** auth/hto.py, auth/dependencies.py, organization models, dashboard auth and security specs.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Replace shared organization credentials with individual accounts and memberships. Implement owner, administrator, billing and member permissions with a server-enforced permission matrix.
2. Add recipient-bound, expiring invitations, membership transitions and administrator MFA enrollment/recovery. Prevent privilege escalation and unsafe loss of the last owner.
3. Enforce tenant authorization in routes, services, workers, exports and resource lookups. Internal operations privilege must remain separate from organization roles.
4. Provide a controlled migration for existing HTO organizations; never promote all historical users to administrators.
5. Keep personal service ownership separate from organization-paid lines and prohibit cross-tenant reassignment by changing a request parameter.

## Acceptance and evidence

- Test cross-tenant IDs, guessed URLs, background jobs/exports, revoked memberships, invitation replay/races and role changes mid-operation.
- Test MFA bypass attempts, recovery and last-owner rules, including users belonging to multiple organizations.

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
