# Refreshed baseline — chunk 01

Recorded 8 September 2026 as the first deliverable of
[chunk 01](chunks/01-scope-and-specifications.md). This file records what was
actually observed on that date. It does not declare any defect fixed, and it
does not certify the branch as release-ready.

## Repository and commit facts

| Fact | Value |
|---|---|
| Remote | `https://github.com/block-sig-hash/damdam.git` |
| Default integration branch | `develop` |
| `origin/develop` after `git fetch --all --prune --tags` on 2026-09-08 | `6790c74707a0f3e52cfedb36bc173ec83ca26663` |
| Commit date of that SHA | 2026-07-28 22:26:52 +0100 |
| Commit subject | `fix(ci): prepare the pilot release candidate (#99)` |
| Base SHA used for chunk 01 | `6790c74707a0f3e52cfedb36bc173ec83ca26663` |
| Latest tag | `v0.1.0-rc.1` |
| Remote branches present | 37, including 20+ unmerged `agent/*` branches |
| Working tree before chunk 01 | clean; no stashes; no other worktrees |

`develop` has not advanced since the 7 September review snapshot, so the base
SHA for this work is identical to the historically reviewed commit. Local work
was preserved: chunk 01 was cut as a new branch,
`chunk/01-scope-and-specifications`, directly from `6790c74`. Nothing was reset,
rebased or force-updated.

### Unmerged remote branches

37 remote refs exist, most of them `agent/*` feature branches that were never
merged into `develop` (for example `agent/us-16-sos`,
`agent/us-18-19-22-sos-dashboard`, `agent/us-06-bulk-package-purchase`,
`agent/deploy-pipeline`, `agent/kuma-monitoring`). None of them were merged,
inspected or rebased by chunk 01. Several implement features that the product
reset retires; chunk 04 owns the decision on what to salvage versus abandon,
and nothing in this pack treats an unmerged branch as delivered behavior.

## Deployment evidence available

| Environment | Evidence found | Date |
|---|---|---|
| staging | GitHub deployments recorded against `develop` | most recent 2026-07-28T21:40:08Z |
| production | no deployment recorded in the queried history | — |

There has been no recorded deployment of any kind since 2026-07-28. The nightly
CI `Deploy develop to staging` job has been **skipped** on every run inspected,
because the API job it depends on fails first. There is therefore no current
running-environment evidence for this baseline — only CI evidence.

## Current CI evidence (observed, not historical)

Nightly scheduled CI runs against `develop` @ `6790c74`. Every run in the
inspected window (2026-09-01 through 2026-09-08) concluded **failure**.

Most recent run at the time of writing —
[run 34198388517](https://github.com/block-sig-hash/damdam/actions/runs/34198388517),
2026-09-08T07:14:54Z, head SHA `6790c74`:

| Job | Conclusion |
|---|---|
| Detect changed paths | success |
| API — Lint, type-check, test | **failure** |
| Mobile — Lint, type-check, test | success |
| Dashboard — Lint, type-check, test | success |
| Docker build check (multi-arch) | success |
| Mobile — iOS screenshot generation (nightly/on-demand) | **success** |
| Mobile — Android screenshot generation | skipped |
| Deploy develop to staging | skipped |

API job detail from that run:

```
FAILED tests/test_auth_api.py::test_otp_request_and_verify_contract
    - app.otp.service.OTPError: invalid_refresh_token
1 failed, 335 passed, 1 warning in 60.80s
Required test coverage of 85.0% reached. Total coverage: 87.13%
```

The failure chain is `jwt.exceptions.ExpiredSignatureError: Signature has
expired` in `apps/api/app/auth/tokens.py:83` → `InvalidRefreshTokenError` →
`OTPError("invalid_refresh_token")` raised from `apps/api/app/auth/routes.py:152`.
This is the clock/expiry defect described as original finding 5. It is
**still failing**; chunk 02 owns the fix.

## Differences from the historical 6790c74 review

The 7 September review recorded "335 API tests passed, one failed, 87% coverage;
iOS screenshot output 0/32; mobile unit and dashboard checks passed", citing
[run 34094962267](https://github.com/block-sig-hash/damdam/actions/runs/34094962267).
Comparing that run against the 2026-09-08 run on the same commit:

| Item | 2026-09-07 (historical review) | 2026-09-08 (observed now) | Assessment |
|---|---|---|---|
| API test result | 1 failed / 335 passed | 1 failed / 335 passed, same test, same error | Unchanged and reproducible |
| API coverage | 87% | 87.13%, threshold 85% met | Unchanged; coverage is not the blocker |
| iOS screenshot job | failure, 0/32 images | **success, 33 PNG files uploaded** (`mobile-screenshots-ios`, artifact 10045606959, 3,368,205 bytes) | **Materially different** |
| Mobile unit / lint / types | success | success | Unchanged |
| Dashboard unit / lint / types | success | success | Unchanged |
| Docker multi-arch build | not separately recorded | success | Additional current evidence |
| Staging deploy | skipped | skipped | Unchanged; blocked behind the API job |

**The one material difference is the iOS screenshot job.** On the identical
commit it failed on 7 September and succeeded on 8 September, producing 33
images. The correct current classification is therefore *intermittent /
environment-dependent*, not *deterministically broken*. The "0/32" figure is a
**historical** observation and must not be repeated as a current fact.

Two consequences for the plan:

1. Chunk 02 must diagnose flakiness and add a nonempty-manifest assertion, not
   only "make screenshots generate". A job that passes some nights and fails
   others without a manifest check is not a trustworthy release gate.
2. The screenshot count is in any case superseded. 33 images belong to the old
   Hajj/SOS/verified-CLI screen matrix. The redesigned screen and locale matrix
   defined in chunk 08 and chunk 27 replaces it; no count carries forward.

Nothing above is a fix. Both original CI findings remain open, one
reproducibly and one intermittently.

## Reproducing this record

```bash
git -C <checkout> fetch --all --prune --tags
git -C <checkout> rev-parse origin/develop
gh run list --limit 8
gh run view 34198388517 --json headSha,conclusion,jobs
gh run view 34198388517 --log-failed
gh api repos/block-sig-hash/damdam/deployments
```

## Known limitation of this checkout

The working checkout used for chunk 01 is `/tmp/damdam-review-20260907`, a full
clone of the remote. `/tmp` is not durable across a host restart. The branch is
committed locally and has **not** been pushed — pushing is an outward-facing
action that was not authorized for this chunk. Relocate or push the branch
before relying on it.
