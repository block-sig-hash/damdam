# Chunk 03 — Prove Telnyx feasibility and document the carrier contract

**Depends on:** chunk 01.
**Plan mapping:** D1/D2 + early PR-09 / US-35.
**Likely starting points:** IMPLEMENTATION-PLAN.md section 5; existing esim/voice provider contracts; current official Telnyx documentation.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Produce a dated capability matrix separating eSIM data, native VoLTE, assigned-number availability, messaging, device support and roaming. Recheck the documented beta status and identify production/resale/support questions.
2. Draft an unsent Telnyx enquiry for the same eSIM providing data and native incoming/outgoing calls, first activation, supported markets, number countries, APIs, usage/caps, and complete call costs TO Nigeria.
3. Record documented request/response and idempotency/lookup contracts with source URLs. Do not invent missing beta endpoints, successful fixtures or universal voice coverage.
4. Create a minimal non-production contract/probe harness using documented APIs and scrubbed fixtures. Live tests require authorized credentials, approved test scope and spending; otherwise deliver the harness and list the exact pending evidence.
5. Record a go/no-go decision per proposed market. Third-party verified caller ID is deferred and is not a launch disqualifier.

## Acceptance and evidence

- Fixture tests are clearly labelled simulations. If authorized live access exists, capture the profile/line correlation and real-device observations without publishing activation secrets.
- Unavailable beta or commercial access leaves D1 open; it must not prevent unrelated foundational chunks. Do not replace carrier voice with WebRTC.

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
