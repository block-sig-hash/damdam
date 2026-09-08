# Chunk 06 — Implement global identity and account recovery

**Depends on:** chunk 04, chunk 05.
**Plan mapping:** PR-03 part A / US-29.
**Likely starting points:** Authentication, OTP/PIN/session services; mobile session storage; security and identity decisions from chunk 01.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Implement the documented launch login/recovery method, using email-based recovery as the proposed default if adopted in chunk 01. Authentication must not depend on retaining an assigned carrier number or retired family/CLI steps.
2. Verify ownership before linking new login identities to existing accounts. Provide safe legacy-account migration and recovery, session rotation/revocation, throttling and account-enumeration resistance.
3. Keep verification tokens single-use, expiring and purpose-bound; store credentials securely and avoid secrets in telemetry.
4. Keep account caches and asynchronous operations scoped across logout/account switches. Expose stable auth contracts for mobile and dashboard.
5. Use a delivery-provider abstraction and test transport; live email delivery approval/configuration remains explicit.

## Acceptance and evidence

- Write auth tests first or alongside implementation under repository policy. Test expired/replayed links, reset races, session invalidation and unverified-email account takeover attempts.
- Test existing users retain access and account switching cannot reveal another user's cached data. Exercise PostgreSQL constraints and relevant mobile session tests.

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
