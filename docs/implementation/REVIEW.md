# Codex review and refactoring assignment

Use this after Claude completes one chunk. The user has authorized Codex to rigorously review and refactor the implementation where needed. Do not merge/deploy or begin the next implementation chunk implicitly.

## Copyable review request

```text
Review DamDam chunk NN using docs/implementation/chunks/, the Claude
handoff and the actual branch/worktree or PR I provide.
Check the code against its acceptance criteria and surrounding integrations.
Independently verify the important behavior and failure cases.
Fix/refactor defects within scope and add meaningful regression coverage.
Do not just list fixable issues. Preserve unrelated work.
Return findings, changes made, checks/results, final head SHA and
ACCEPTED / CHANGES_REQUIRED / EXTERNAL_BLOCKED with explicit remaining gates.
Do not merge, deploy or start the next chunk.
```

Supply the branch/worktree or PR link and base/head SHA with this request.

## Review procedure

1. Read repository instructions, the chunk, accepted dependency records and Claude's handoff. Confirm the base/head and local changes; do not review a stale diff.
2. Independently inspect changed code plus call sites, background jobs, routes, client use, permissions, configuration and migration implications. Trace the main journey through module boundaries.
3. Check each acceptance criterion. Distinguish missing implementation, incorrect behavior, missing test coverage and external evidence gaps.
4. Exercise important negative cases and failures independently. Reuse existing tests where appropriate; add regression tests that would fail on the actual defect.
5. Refactor in scope for correctness/maintainability: simplify duplicated state transitions, improve transaction boundaries, repair error propagation and authorization, or remove obsolete dependencies. Avoid unrelated stylistic rewrites.
6. Re-run affected checks after fixes. Broaden only when changes or unresolved concerns warrant it. Preserve required CI/coverage/contract safeguards.
7. Inspect rendered UI for UI chunks, including error/loading/empty states and localization. Inspect native behavior on actual devices when the criterion requires it; no screenshot can prove a native call.
8. Record results against the exact final SHA, including uncommitted changes if any. Save the review under `docs/implementation/reviews/NN.md` and update STATUS.md after an evidence-based decision.

## Risk-specific checks

- Identity/tenancy: ownership, account linking/recovery, MFA/session revocation, object-level authorization, worker/export access and negative cross-tenant requests.
- Money/payments: exact units/currencies, immutable seller and quote, balanced ledger entries, authentic webhooks, concurrency, retry after unknown charge and original-reference refunds.
- Orders/carriers: operation identity persisted before side effects, accepted-but-response-lost, crash recovery, no premature supplier failover, supported documented contracts and state separation.
- Usage/controls: cumulative versus incremental readings, replay/late corrections, tariff versions, stale balances, actual carrier enforcement and delayed-usage liability.
- Migrations/removal: old-data upgrade, legacy clients/jobs, retained ownership, no lost history, no orphaned dispatch, retention and recovery.
- Enterprise: person versus member role, recipient-bound allocation, bulk partial failure, offboarding and personal/work service separation.
- UI: reachable complete journeys, persistent recovery, accessible rendered states, English/French, secure activation details and no unsupported installation promises.
- Operations/release: secrets/log redaction, production mock rejection, restore proof, missing-gate failure and matching commit/config evidence.

## Finding and acceptance format

For each finding: severity, file/line, concrete trigger, user/business impact, evidence, fix and regression result. Prefer demonstrated defects over speculative warnings. A checklist is useful evidence organization, not a substitute for judgment.

Conclude with:
- **Accepted scope and final SHA**, or exact blocking defects/missing evidence.
- **Refactors/fixes made** and why.
- **Tests actually run** and practical limits.
- **External gates still open**, separately from software defects.
- **Next eligible chunk**, only if the necessary dependencies are accepted.

P0/P1 defects and material P2 gaps in correctness, authorization, financial integrity, data preservation or required behavior block acceptance. Missing mandatory verification blocks the affected scope. Refactoring suggestions that do not affect acceptance can be explicitly deferred with ownership.

If a necessary live/native test cannot run, do not falsely accept the whole chunk. Accept a clearly named software/preparatory subchunk only when its own criteria pass, leaving the remainder visible. No code-quality verdict implies production readiness.

