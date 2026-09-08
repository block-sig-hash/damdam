# Chunk 01 — Reset product specifications and working rules

**Depends on:** none.
**Plan mapping:** PR-01 / US-27.
**Likely starting points:** AGENTS.md; docs/README.md; product, API, data, frontend, security, testing and release specifications.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Refresh the available develop/CI baseline without overwriting local work; record the actual base SHA, deployment evidence available, and differences from the historical 6790c74 review.
2. Copy this supplied build pack into docs/implementation, including IMPLEMENTATION-PLAN.md. Reconcile active specs with the global consumer/enterprise carrier-voice product; retain historical amendments and story IDs.
3. Register stories/acceptance criteria for every chunk. Reuse the proposed US-27–US-43 mapping only if those IDs remain available; record any new IDs rather than overwriting existing stories.
4. Update AGENTS.md to the user's explicit workflow: Claude implements, Codex independently reviews and may refactor. Replace obsolete supplier/feature-freeze/ownership assumptions while retaining abstraction, security, migration and relevant testing requirements.
5. Record D1–D6 owners, required evidence and unresolved decisions. Mark full check-in/welfare removal, email recovery, new assigned number and prepaid charging as proposed defaults where the plan does, rather than inventing founder approval. Plan retirement around the accepted scope.
6. Update docs index, affected current specs and release criteria coherently. Define module ownership and the revised user journeys; no application code or broad architecture rewrite.

## Acceptance and evidence

- Trace each of the five original repo findings to a chunk and acceptance test. Search active specs for contradictory Hajj/family/SOS/WebRTC/verified-CLI/HTO assumptions and explicitly classify remaining historical references.
- Document the current failures as observed or historical, never as fixed. Validate documentation links and existing documentation checks.

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
