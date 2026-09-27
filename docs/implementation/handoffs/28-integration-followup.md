# US-43 integration follow-up — combined regressions and WAL-G CI fixture

Prepared 27 September 2026 on `followup/ci-integrated-regressions`, stacked on
chunk 30 draft PR #137 as [draft PR #138](https://github.com/block-sig-hash/damdam/pull/138).
Code head before this documentation record: `9e29ec8baa96dc07b62b7ad83e6ae236261e8b89`.
This is **READY_FOR_REVIEW**, not a new release acceptance or merge approval.

## What changed

- The test-only WAL-G Compose overlay builds a MinIO image from the official
  [server](https://github.com/minio/minio/releases/tag/RELEASE.2024-11-07T00-52-20Z)
  and [client](https://github.com/minio/mc/releases/tag/RELEASE.2024-11-21T17-21-54Z)
  release assets, pins their release versions and verifies each published
  SHA-256 before execution. This replaces Quay tags that returned
  `unauthorized` in chunk 30 CI. The production Compose file and R2
  configuration are unchanged. This old release is an isolated CI fixture,
  not a proposed production object-store version.
- The checkout PostgreSQL suite now connects a real quote and order to its
  captured payment attempt, settled refund and opposite immutable ledger
  posting across process/session boundaries. It checks replay does not create
  another order, charge, payout or posting. The fixture's ledger tables are
  truncated between tests; the first full run exposed leftover funding state.
- The enterprise suite now joins CSV preview/apply, partial per-person funding,
  fixture-confirmed provisioning, offboarding and the historical departmental
  report through one database history. It checks the remaining employee is
  active and the departed employee's local grant expires without erasing the
  original purchase. The supplier confirmation is synthetic.
- The calling suite now races mobile- and browser-labelled credentials against
  one shared balance, refuses copied device grants, then authorizes the other
  client only after the first hold is released. These are backend policy tests,
  not V04/V05 SDK/media or real call evidence.

## Verification

| Check | Result |
|---|---|
| Three affected PostgreSQL test modules in an isolated local database | PASS, 84 tests collected |
| Ruff on changed API test modules | PASS |
| Compose overlay validation, `sh -n scripts/test-walg-pitr.sh`, `git diff --check` | PASS |
| Local `./scripts/test-walg-pitr.sh` with the newly built verified fixture | PASS: `PITR_PROOF=PASS`, `PITR_RECONCILIATION=PASS`, 11-second recovery, no post-target transaction or unbalanced entry |
| [Clean-runner on-demand CI](https://github.com/block-sig-hash/damdam/actions/runs/36289126468) at `9e29ec8` | API PASS: 1,736 passed, 5 skipped, 89.93% coverage; Docker/PITR PASS: archive interval 48 seconds, recovery 7 seconds, both proof and reconciliation markers; dashboard, docs, mobile lint/test and release validator PASS. Android/iOS screenshot jobs still running when this record was updated; final workflow conclusion must be checked before acceptance. |

The local test database is `damdam_review_combined_20260925` on the existing
dedicated PostgreSQL test container; no production data was used or changed.
The PITR drill removes only its own isolated Compose containers, volumes and
network when it exits.

## Open scope

These regressions close three **service-level joined-state test gaps**, not the
complete chunk 28 journeys. Mobile/dashboard UI and API delivery together,
actual merchant/carrier/calling adapters, late supplier CDRs, deployed old
clients, representative staging migration rollback and physical eSIM/data/
native-call evidence remain open. The founder has not approved EAS signing,
testers, live pilot access or a spending limit; the chunk 30 NO-GO decision is
unchanged. No merge, deployment, store submission or live spend was performed.
