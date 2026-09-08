# Claude implementation handoff

Fill this out for one chunk. Save a sanitized copy in `docs/implementation/handoffs/NN.md`. Do not include API keys, real activation codes, customer records or private payment payloads.

## Identity

- Chunk and registered story:
- Branch/worktree path; PR link if one exists:
- Base SHA:
- Head SHA:
- Working tree clean/dirty; exact uncommitted changes:
- Accepted dependency review references:
- Status: READY_FOR_REVIEW / EXTERNAL_BLOCKED / incomplete

## Result

Describe the previous behavior, resulting behavior and why this implementation satisfies the chunk. List affected modules, public contracts and deliberately deferred items. Explain deviations from the assignment.

## Acceptance evidence

| Criterion | Test or manual procedure | Result | Evidence path |
|---|---|---|---|
| Each criterion from the chunk | Exact test/procedure | PASS / FAIL / NOT RUN | Sanitized artifact |

State what is simulated, sandbox, staging or physical/live. Record environment and configuration versions needed to reproduce it. Distinguish observed behavior from documentation claims.

## Checks actually run

| Command and working directory | Result / exit code | Relevant output or artifact |
|---|---|---|
| Exact command | Actual result | Summary/log path |

Include meaningful regression tests, relevant existing suites, lint/types/build/contract checks. Record unavailable dependencies, environment failures, skipped checks and remaining failures explicitly. Do not claim checks passed because another branch passed them.

## Migrations and compatibility

- Fresh install and old-data upgrade results:
- Backfill/dry-run, constraints and historical data preserved:
- Old-client/worker compatibility:
- Rollback or roll-forward procedure and irreversible steps:
- Configuration changes and secret names only:
- Dependency changes and deployed architecture support:

## UI or integration evidence

- Screenshots/device/viewport/locale and accessibility observations:
- Contract documentation source and checked date:
- Fixture versus actual provider response:
- Physical device/network/payment evidence if authorized:
- Sensitive fields excluded/redacted:

## Known gaps and handoff

- Open defects and their impact:
- External gates/decisions, exact missing input and owner:
- Remaining test/evidence work:
- Refactoring concerns or tradeoffs for Codex:
- No merge/deployment/store submission performed unless separately authorized:

Claude's handoff is a request for review, not acceptance.
