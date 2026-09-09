# Chunk 02 accepted review and integration handoff — US-42

Final evidence review: 9 September 2026. Codex independently reviewed and fixed
chunk 02. **ACCEPTED** for its assigned CI/auth/screenshot scope; broader US-42
release and environment criteria remain assigned to later chunks.

## Exact state

- Repository: `/tmp/damdam-review-20260907`.
- Branch: `chunk/02-ci-baseline`.
- Accepted predecessor: `178c448d503eb2c5733c2daa7e12ce65159be769`.
- Corrected executable content: `4e5ecc9a55b4230c1b73923eff08fbf41b7f64bf`.
- Tested CI head: `aeb74f6bc46a18bfdd2fecf19b21560fb360568b`.
- The final acceptance commit changes documentation only. Resolve the current
  full branch SHA with `git rev-parse`; verify any later executable changes.
- [Independent review](../reviews/02.md) contains findings, fixes, evidence and
  remaining limitations. Do not restart from Claude's submitted `2aabc22` head.
- Chunk 01 merged as `dffff91edc22b2c8c2d1724f4da27589bf2ec77a` in
  [PR #100](https://github.com/block-sig-hash/damdam/pull/100).
- [PR #101](https://github.com/block-sig-hash/damdam/pull/101) carries chunk 02;
  consult its current state for merge status and final head checks.
- Durable bundle: `/home/iadamu/damdam-chunk02-accepted.bundle`, containing both
  reviewed branches. The earlier `/home/iadamu/damdam-chunk02-reviewed.bundle`
  preserves the initial externally blocked review snapshot.
- `/tmp/damdam-chunk03` remains a separate worktree based on accepted chunk 01.
  Codex has not reviewed or modified that independent implementation here.

## Passing evidence

API: 359 tests, 87.65% coverage (unchanged 85% threshold), migrations, lint, types
and OpenAPI drift. Mobile: 415 tests, one existing skip, lint/types and Android
debug build. Dashboard: 66 tests, lint/types; production build also passed locally.
Docker: API and Postgres amd64/arm64 builds, real readiness checks and WAL-G
point-in-time restore. Documentation links and workflow YAML checks pass.

[PR CI 34268255191](https://github.com/block-sig-hash/damdam/actions/runs/34268255191)
and [on-demand CI 34268285562](https://github.com/block-sig-hash/damdam/actions/runs/34268285562)
both pass at `aeb74f6`; the latter includes iOS. Downloaded artifacts independently
validate as 32 readable expected PNGs per platform. Each JUnit report has 16
successful flows, zero failures/errors. Sample English/French renders were
visually inspected. This is simulator/emulator proof of the baseline harness,
not physical carrier-service proof or a guarantee against future intermittent
startup failures.

## Integration procedure if resuming before merge

The user already authorized publishing and merging one PR per reviewed chunk.
GitHub owner access is restored; chunk 01 is merged. For chunk 02:

1. Inspect the current branch and PR. Preserve unrelated work. Confirm that all
   changes after tested `aeb74f6` are documentation only; otherwise revalidate.
2. Wait for the final documentation head's applicable PR checks. Keep all checks
   enforcing failures. Mark ready and merge #101 with a merge commit once checks
   pass and no blocking findings remain; match the exact reviewed branch head.
3. Fetch and verify the resulting develop commit contains accepted chunk 02.
   Its push-only staging job may fail for the known missing secrets below.
   Report that separately from passing verification. Do not bypass checks,
   promote main, change release gates or claim production deployment.

## External setup still required

Staging run [34268870406](https://github.com/block-sig-hash/damdam/actions/runs/34268870406)
failed before deployment: `STAGING_OCI_HOST`, `STAGING_OCI_DEPLOY_USER`,
`STAGING_OCI_SSH_KEY` and `STAGING_API_BASE_URL` are unset. The founder/environment
owner must configure the actual staging service securely (D6/chunk 26). No secret
values belong in this handoff or chat. The fail-fast gate remains unchanged.

The automated Claude job on #101 skipped analysis under its workflow-change
trust restriction despite reporting green. It does not replace the independent
Codex review; no restriction was bypassed. Full US-42 production/signing/release
acceptance remains with later chunks.

Chunk 03 depends only on chunk 01 and can finish independently. Its
[assignment](../chunks/03-telnyx-feasibility.md) remains the dated capability
matrix, unsent enquiry and non-production probe harness; do not invent live
carrier support or replace native voice with app VoIP. Chunks 04/05 can use the
integrated accepted chunk 02 baseline, subject to their own decision gates.
