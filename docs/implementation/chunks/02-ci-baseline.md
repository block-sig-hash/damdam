# Chunk 02 — Repair the CI baseline and screenshot harness

**Depends on:** chunk 01.
**Plan mapping:** PR-16 early / US-42.
**Likely starting points:** .github/workflows; docs/testing-qa.md; auth tests; screenshot scripts and native build configuration.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Reproduce current baseline failures before fixing them. Investigate the historical JWT July-versus-September clock mismatch using the actual current branch.
2. Use one controlled clock consistently for test token creation and validation; keep production expiry enforcement intact.
3. Diagnose intermittent iOS screenshot execution and artifact collection using the failed and successful runs. Both platforms already enforce an exact count of 32 PNGs; strengthen that check into exact expected screen/locale coverage with nonempty valid images. The successful September 8 upload was 32 PNGs plus an XML report, not 33 PNGs. Validate a nonempty, complete manifest against an explicit current screen/locale matrix; do not hardcode the historical 32 count as a permanent target.
4. Record reproducible toolchain/environment requirements and distinguish missing macOS/signing/secrets from application failures. Keep required checks enforcing failures.
5. Wire the documentation-link check into a docs-triggered CI path and clarify that any automated Claude review is supplemental to the required independent Codex acceptance. Preserve the required check names and do not change production release-promotion semantics in this chunk.

## Acceptance and evidence

- Test valid and expired tokens plus time boundaries. Demonstrate screenshot validation rejects an empty directory, a missing expected image replaced by an unrelated PNG at the same count, and an empty/corrupt expected PNG. Test both platform matrices and keep harness-only test changes out of the production app behavior.
- Run applicable API/mobile/dashboard baseline checks; use macOS CI for iOS evidence if available. Unavailable native execution remains an explicit evidence gap.

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
