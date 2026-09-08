# Refreshed baseline — chunk 01

Recorded 8 September 2026; corrected by independent Codex review on the same
date. This is a dated observation, not a production-readiness certificate.
The original builder handoff remains historical; corrections here govern later work.

## Repository and commit facts

- Repository: `block-sig-hash/damdam`; integration branch: `develop`.
- Base and fetched `origin/develop`: `6790c74707a0f3e52cfedb36bc173ec83ca26663`.
- Base subject: `fix(ci): prepare the pilot release candidate (#99)`.
- Base commit date: 2026-07-28; historical tag `v0.1.0-rc.1` remains untouched.
- Builder content: `0f3331a907783edc75663ded8e6cc85208961ec9`; handoff-only
  successor: `3e99cefcda288747fb8cfe15adaaf9e0ff6d0fc3`.
- Branch: `chunk/01-scope-and-specifications`, local only. The checkout was clean
  when independent review began. Review fixes follow those commits.

The checkout has 37 remote refs including `origin/HEAD`. Many feature tips are
not ancestors of `origin/develop` according to `git branch -r --no-merged`.
That does not prove their changes never landed: squash/rebase merges may retain
non-ancestor branch tips. Inspect code and PR history before salvaging anything;
do not treat branch names or ancestry alone as implementation evidence.

## Deployment records and their limits

Independent review queried `gh api
'repos/block-sig-hash/damdam/deployments?per_page=100'` on 8 September. It returned
19 records, including:

| Environment | Latest returned record | SHA | Meaning |
|---|---|---|---|
| staging | 2026-07-28T21:40:08Z; ID 5647994259 | `6790c74` | A deployment record exists |
| production | 2026-07-12T22:46:45Z; ID 5416936363 | `76a8b1ad5b0bbbfe8c6806d9cc20e610fb40435c` | A production deployment record exists |

The initial handoff's claim that production had no deployment record was wrong.
No later record appeared in this response. A record is not proof that deployment
succeeded or that an environment is healthy now; statuses, host health, secrets
and running versions were not verified by this review.

`.github/workflows/ci.yml` allows `deploy-staging` only on a **push** to
`refs/heads/develop`, with no failed/cancelled prerequisites. Scheduled runs
therefore skip it even if tests pass. An API failure also blocks an eligible
push deployment; fixing that failure alone will not make a scheduled run deploy.

## CI evidence

[Run 34198388517](https://github.com/block-sig-hash/damdam/actions/runs/34198388517)
started 2026-09-08T07:14:54Z against `6790c74` and concluded failure. Independent
review confirmed job/step conclusions with `gh run view --json headSha,conclusion,jobs`.

| Job | Conclusion |
|---|---|
| Detect changed paths | success |
| API lint/types/migrations | success |
| API pytest | failure |
| OpenAPI drift | skipped after pytest failed; not independently proven passing |
| Mobile lint/types/tests + Android debug compilation | success |
| Dashboard lint/types/tests | success; no production build step in this job |
| Docker multi-architecture checks | success |
| iOS screenshot job | success |
| Android screenshot job | skipped |
| Staging deploy | skipped under the push-only event condition |

The builder reported this API log result from that run:

```
FAILED tests/test_auth_api.py::test_otp_request_and_verify_contract
    - app.otp.service.OTPError: invalid_refresh_token
1 failed, 335 passed, 1 warning in 60.80s
Required test coverage of 85.0% reached. Total coverage: 87.13%
```

The reported chain is `ExpiredSignatureError` → `InvalidRefreshTokenError` →
`OTPError`. Chunk 02 must reproduce/fix the shared test clock while preserving
production token expiry. No application test was rerun during this docs review.

### Screenshot correction: 32 PNGs, not 33

Independent review read the existing
[iOS job log](https://github.com/block-sig-hash/damdam/actions/runs/34198388517/job/101971247184).
At 07:40:31 it reports `Expected 32 screenshots; found 32`. The subsequent upload
reports **33 files** because the workflow includes 32 PNGs **and
`maestro-report.xml`**. Artifact ID 10045606959 is 3,368,205 bytes. The upload's
file count is not a PNG count.

Both Android and iOS already have an exact-count assertion in `ci.yml` and
`if-no-files-found: error` on artifact upload. The empty artifact failure was
already visible to CI; chunk 02 must not claim to add missing nonempty enforcement.

The [September 7 run](https://github.com/block-sig-hash/damdam/actions/runs/34094962267)
was reported with 0/32 PNGs and a failed iOS job, while September 8 succeeds on
the same application commit. This establishes differing outcomes, not the root
cause. Chunk 02 owns diagnosis of harness/runner/toolchain variability and
strengthening count-only checking to exact screen/locale coverage and valid,
nonempty images. Test a missing expected image replaced by an unrelated image
at the same count. Chunk 08 defines the revised matrix; chunk 27 enforces it for
release. Neither old count is a permanent target for the redesigned app.

## Release enforcement: repository code versus server settings

The checked-in promotion workflow runs the existing signoff validator on PRs to
`main`. Its matrix includes old app-call, CallKit/PushKit, check-in/SOS and HTO
scenarios. That matrix remains a legacy compatibility constraint until chunk 27
updates template and validator together. Do not use it to certify the reset
product or fabricate obsolete evidence.

The July infrastructure amendment records branch-protection enforcement at that
time. Independent review's GET of `repos/block-sig-hash/damdam/branches/main/protection`
returned **404** on 8 September. This does not establish current enforcement or
its absence; classic protection, rulesets and account access require separate
verification. No server setting was changed. Chunk 27 must verify actual
promotion protection before release.

The legacy validator checks whether PASS or FAIL text exists, rather than
requiring every mandatory result to pass. It also accepts any tested ancestor
without excluding later runtime changes. Chunk 27's negative cases explicitly
cover these limitations, future dates and missing evidence. This review leaves
runtime release automation unchanged and does not authorize promotion.

## Reproduction and source limits

```
git rev-parse origin/develop
git branch -r --no-merged origin/develop
gh run view 34198388517 --repo block-sig-hash/damdam --json headSha,conclusion,jobs
gh run view 34198388517 --repo block-sig-hash/damdam --job 101971247184 --log
gh api 'repos/block-sig-hash/damdam/deployments?per_page=100'
gh api repos/block-sig-hash/damdam/branches/main/protection
```

The initial handoff reported failures on the September 1–8 runs. Independent
review checked the named September 8 run, not every run in that window. The
original five findings remain implementation work; none is fixed by this review.

## Durability

The working checkout is `/tmp/damdam-review-20260907`. A local bundle under the
user's home directory preserves the reviewed branch; see the review handoff for
the exact filename/head. No push, merge, deployment or live test occurred.

---

## Chunk 02 addendum — 8 September 2026

Appended by chunk 02 (US-42). Everything above is the chunk 01 record as
independently reviewed and accepted; nothing above has been rewritten. This
section records only what changed afterwards.

| Baseline item above | Status after chunk 02 |
|---|---|
| API `test_otp_request_and_verify_contract` failing | **Fixed in this branch, not yet on `develop`.** Reproduced locally first, then fixed. Full local suite: 343 passed, 0 failed, coverage 87.58%. See `docs/testing-qa.md` §14.14.1. |
| iOS screenshot job intermittent | **Diagnosed; mitigation committed, unverified.** Root cause is Maestro's XCUITest driver startup timing out on the macOS runner (`IOSDriverTimeoutException` at ~2m36s on 09-07 versus a ~64s healthy startup on 09-08). `MAESTRO_DRIVER_STARTUP_TIMEOUT` is now set. **No macOS CI was available to confirm the mitigation** — this remains an evidence gap. See §14.14.3. |
| Count-only screenshot assertion (`-eq 32`) | **Replaced** by exact matrix validation derived from the Maestro flows, with structural PNG checks and negative tests. The derived matrix independently reproduces 32 per platform, which is how the previous hardcoded figure was confirmed rather than assumed. See §14.14.2. |
| OpenAPI drift "skipped after pytest failed; not independently proven passing" | **Now proven passing locally** — the drift check runs and reports no drift. Chunk 02 changes no route signature or schema. |
| Staging deploy skipped | **Unchanged and correct.** Deployment is push-only by design; scheduled runs cannot deploy. Chunk 02 did not alter that policy. |
| Production deployment history / branch-protection 404 | **Unchanged.** Not re-queried by chunk 02; still chunk 27's verification. |

No claim here is a claim about `develop`: these results are from the
`chunk/02-ci-baseline` branch and from local execution. CI on this branch has
not been run, because the branch has not been pushed.
