# Chunk 05 — Introduce core domain models and migration boundaries

**Depends on:** chunk 01, chunk 02.
**Plan mapping:** PR-02 / US-28.
**Likely starting points:** Current auth/packages/manifests/payment/esim models and migrations; docs/data-model.md and api-spec.md.
Paths refer to the inspected baseline; verify them in the actual current checkout.

## Outcome and implementation scope

1. Define minimal identities for seller, payer, recipient, organization, product, order item, eSIM profile, carrier line, assigned number and entitlement. Reuse existing identifiers where compatible.
2. Separate payment, provisioning, installation, activation and network states. Specify invariants and ownership without creating an all-purpose status field.
3. Add only the schema/contracts needed to anchor subsequent chunks, with documented nullable/backfill/constraint phases. Detailed auth, ledger and carrier behavior remains in its own chunk.
4. Preserve NGN amounts, original seller/provider references and historical receipts. Keep money currency-explicit; define exact decimal rates and currency-specific scaling.
5. Add numbered schema amendments, API contract changes where applicable and an upgrade/roll-forward plan using representative legacy records.

## Acceptance and evidence

- Test fresh database creation and upgrade from the existing schema with personal users, HTO organizations, paid orders and pending jobs.
- Verify identifier/history preservation, referential constraints and invalid-state rejection. Document irreversible migration steps and data-preserving recovery.

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
