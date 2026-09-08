# Chunk 02 review and publication continuation — US-42

Date: 8 September 2026. Codex independent review.

## State to preserve

- Repository: `/tmp/damdam-review-20260907`.
- Branch: `chunk/02-ci-baseline`.
- Accepted predecessor branch: `chunk/01-scope-and-specifications` at
  `178c448d503eb2c5733c2daa7e12ce65159be769`.
- Reviewed/fixed executable content:
  `4e5ecc9a55b4230c1b73923eff08fbf41b7f64bf`.
- The branch tip following that content adds documentation only: the independent
  review, status and this handoff. Resolve its full SHA with `git rev-parse`;
  do not restart from Claude's original handoff SHA.
- [Independent review](../reviews/02.md): **EXTERNAL_BLOCKED** for whole chunk 02;
  all identified software findings fixed, local regressions pass, remote/native
  checks remain open.
- Chunk 03 has an independent worktree at `/tmp/damdam-chunk03`, based on accepted
  chunk 01. Do not reset, rebase or absorb its work as part of this continuation.
- Durable bundle: `/home/iadamu/damdam-chunk02-reviewed.bundle`, containing both
  reviewed chunk branches. Verify its advertised refs before restoring it.

## What passed

API: 359 tests, 87.65% coverage against the unchanged 85% threshold; migrations,
ruff, mypy and OpenAPI drift pass. A strengthened concurrency test was rerun on
PostgreSQL; all 16 review cases pass, versus nine failures on submitted code.
Mobile: 74 suites, 415 tests and one pre-existing skip; lint/types pass. The
29-test screenshot suite and real historical iOS artifact validation pass.
Dashboard: 17 suites/66 tests, lint/types and production build pass. Compose
configuration and workflow YAML parsing pass. The API Docker build passes for
both linux/amd64 and linux/arm64; API import and OpenAPI generation also pass
inside each image with networking disabled. Full GitHub build/restore evidence
remains open.
All 239 relative documentation links and `git diff --check` pass after review
metadata.
These are local results; no new branch CI or native capture is claimed.

## Publishing and merging — already authorized, currently access-blocked

The user requested one reviewed PR per chunk, then merging after required checks.
Do not wait until chunks 01–05 are one large change. GitHub currently denies write
access to `Align3` (403; viewerPermission READ). The founder must grant access or
authenticate local gh with an authorized account. Do not ask for a token in chat.
No push, PR creation, merge or deployment has succeeded during this review.

Once access is available:

1. Inspect both branches and fetch origin; preserve unrelated changes. Verify
   that chunk 01 still points to its accepted head and that chunk 02 contains
   `4e5ecc9` with no later executable change needing revalidation.
2. Push the two named branches and open separate draft PRs targeting `develop`.
   Use `docs/implementation/pr-drafts/01.md` and `02.md` as `--body-file` content.
   If chunk 01 has not merged yet, disclose that chunk 02 includes its ancestry;
   its PR diff will narrow after a merge preserving that ancestry. A PR based on
   the chunk 01 feature branch would not trigger the current develop/main-only
   pull_request CI, so use develop and state the dependency.
3. Dispatch `ci.yml` on the chunk 02 branch to exercise iOS, which normally runs
   only on schedule or workflow_dispatch. Review the complete required PR jobs,
   Android and iOS captures, complete manifests and build/restore evidence.
   A dispatch/PR run cannot deploy staging under the existing push-only policy.
4. Fix actual failures; retain all checks and thresholds. Record run URLs and
   tested SHA. Distinguish runner/access failures from code defects. A successful
   run demonstrates operation on that runner, not elimination of all flakiness.
5. Update independent review/status once required evidence passes, including
   any materially changed code. Mark PRs ready and merge 01 then 02 when each
   PR's branch rules and review conditions permit. Prefer merge commits to
   preserve reviewed ancestry; re-check the narrowed chunk 02 diff and CI after
   the first merge. Never bypass required reviews or merge while required checks
   are red/pending. If the repository requires a different merge method,
   deliberately transplant only chunk 02's changes and revalidate the result.
6. Verify develop's resulting SHA and checks. Its existing push workflow may
   deploy staging; report its actual result. Do not promote main, alter the
   release-signoff gates, deploy production or claim production readiness.

The user's merge authorization remains valid when access is repaired; it does
not waive checks. Until this evidence is available, do not treat chunk 02 as
accepted or start its dependent chunks 04/05 automatically.

## Chunk 03 independence

The requested start prompt was provided before this review, using only accepted
chunk 01 at `178c448d503eb2c5733c2daa7e12ce65159be769`. Its complete assignment is
[chunks/03-telnyx-feasibility.md](../chunks/03-telnyx-feasibility.md). It prepares
current official-source evidence, an unsent Telnyx enquiry and a non-production
probe harness. No external enquiry, paid test, commercial approval or live
carrier capability is implied. D1/D2 stay open where evidence is missing; native
voice must not silently be replaced with app VoIP. Return its separate handoff
for independent review when complete.
