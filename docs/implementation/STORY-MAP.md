# Story register and traceability map

Opened by [chunk 01](chunks/01-scope-and-specifications.md) on 8 September 2026.

Stories themselves — with full acceptance criteria — are registered in
[`../prd.md`](../prd.md) §10, which is where `AGENTS.md` tells every agent to
look for a `US-XX`. This file is the routing layer: it maps each of the 30 build
chunks to its registered story, and traces the five original review findings to
a chunk and a named acceptance test.

## Story-ID collision check

Checked on the actual base commit `6790c74`, across all of `docs/*.md` and
`create-issues.sh`:

- **In use:** `US-01` … `US-26`. No gaps, no duplicates.
- **Free:** `US-27` and above.

The plan's proposed `US-27`–`US-43` mapping was therefore adopted unchanged. No
new ID was invented and **no existing ID was reused or overwritten**. `US-01`–
`US-26` are retained as historical references; their retained / replaced /
retired disposition is in [`../prd.md`](../prd.md) §10.4.

## Chunk → story map

Several chunks share a story: the plan's `US-27`–`US-43` are PR-sized, while the
30 chunks are smaller review units cut from those PRs. Every chunk has exactly
one registered story. A chunk's own acceptance criteria live in its file under
[`chunks/`](chunks/); the story states the criteria that must hold across all of
its chunks.

| Chunk | Story | Parent PR | Chunk acceptance criteria |
|---|---|---|---|
| 01 Reset product specifications and working rules | US-27 | PR-01 | [chunks/01](chunks/01-scope-and-specifications.md) |
| 02 Repair the CI baseline and screenshot harness | US-42 | PR-16 | [chunks/02](chunks/02-ci-baseline.md) |
| 03 Prove Telnyx feasibility | US-35 | PR-09 | [chunks/03](chunks/03-telnyx-feasibility.md) |
| 04 Retire family, safety and app-calling features safely | US-30 | PR-04 | [chunks/04](chunks/04-safe-feature-retirement.md) |
| 05 Core domain models and migration boundaries | US-28 | PR-02 | [chunks/05](chunks/05-core-schema.md) |
| 06 Global identity and account recovery | US-29 | PR-03 | [chunks/06](chunks/06-identity-and-recovery.md) |
| 07 Memberships, tenant isolation and administrator MFA | US-29 | PR-03 | [chunks/07](chunks/07-organizations-and-rbac.md) |
| 08 Consumer and enterprise design system | US-27 | PR-01 | [chunks/08](chunks/08-design-system.md) |
| 09 Supported-market catalog and immutable quotes | US-31 | PR-05 | [chunks/09](chunks/09-catalog-and-quotes.md) |
| 10 Multi-currency ledger and atomic reservations | US-32 | PR-06 | [chunks/10](chunks/10-ledger-and-reservations.md) |
| 11 Order orchestration and durable recovery | US-32 | PR-06 | [chunks/11](chunks/11-orders-and-durable-recovery.md) |
| 12 Payment routing and Paystack modernization | US-33 | PR-07 | [chunks/12](chunks/12-payment-routing-and-paystack.md) |
| 13 Selected global payment adapter and wallet checkout | US-33 | PR-07 | [chunks/13](chunks/13-global-checkout.md) |
| 14 Refunds, disputes, bank funding and receipts | US-34 | PR-08 | [chunks/14](chunks/14-refunds-and-reconciliation.md) |
| 15 Telnyx eSIM, line and number lifecycle | US-35 | PR-09 | [chunks/15](chunks/15-telnyx-line-lifecycle.md) |
| 16 Usage reconciliation and carrier charging | US-36 | PR-10 | [chunks/16](chunks/16-usage-and-charging.md) |
| 17 Top-ups, spending controls and suspension | US-36 | PR-10 | [chunks/17](chunks/17-spending-controls-and-topups.md) |
| 18 Mobile navigation, onboarding and redemption | US-37 | PR-11 | [chunks/18](chunks/18-mobile-navigation-and-onboarding.md) |
| 19 Consumer purchase journey | US-37 | PR-11 | [chunks/19](chunks/19-mobile-plans-and-checkout.md) |
| 20 My Line, eSIM installation and native-call guidance | US-38 | PR-12 | [chunks/20](chunks/20-mobile-my-line-and-installation.md) |
| 21 Account, receipts, support and deletion | US-38 | PR-12 | [chunks/21](chunks/21-mobile-account-and-support.md) |
| 22 Enterprise people, teams and validated imports | US-39 | PR-13 | [chunks/22](chunks/22-enterprise-people-and-imports.md) |
| 23 Enterprise bulk orders, assignment and activation | US-40 | PR-14 | [chunks/23](chunks/23-enterprise-bulk-provisioning.md) |
| 24 Enterprise funding, budgets, reports and offboarding | US-40 | PR-14 | [chunks/24](chunks/24-enterprise-billing-and-offboarding.md) |
| 25 Internal support and exception operations | US-41 | PR-15 | [chunks/25](chunks/25-internal-operations.md) |
| 26 Environments, backups and operational visibility | US-42 | PR-16 | [chunks/26](chunks/26-production-environment-and-observability.md) |
| 27 Signed builds, privacy disclosures, release automation | US-42 | PR-16 | [chunks/27](chunks/27-native-builds-and-release-gates.md) |
| 28 Integrated flows, migrations and failure recovery | US-43 | PR-17 | [chunks/28](chunks/28-integration-and-failure-testing.md) |
| 29 Physical-device and enterprise pilot | US-43 | PR-17 | [chunks/29](chunks/29-physical-device-and-enterprise-pilot.md) |
| 30 Release findings and production handoff | US-43 | PR-17 | [chunks/30](chunks/30-release-candidate-and-handoff.md) |

Chunk 08 is mapped to `US-27` rather than a story of its own because the design
system is a specification artifact, exactly like the rest of the product reset —
its acceptance is "the redesigned system exists and the screen/locale matrix is
defined", which is `AC-27.6`.

## Five original findings — mandatory traceability

None of these is fixed. Every row states the current status observed on
2026-09-08 (see [BASELINE.md](BASELINE.md)), the chunk that owns it and the named
acceptance test that closes it.

### Finding 1 — offline events can sync as the wrong signed-in user

- **Status:** open, historical observation from the 7 September review; not
  independently re-observed by chunk 01, and not fixed.
- **Owning chunk:** 04 (safe retirement). Retained caches also 06 and 21.
- **Story:** `US-30`, criterion `AC-30.4`.
- **Acceptance test:** account-switch isolation — user A queues an offline
  event, signs out; user B signs in; no A event is ever dispatched or attributed
  as B. Must hold across app restart and across a delayed provider callback that
  arrives after the switch. Legacy rows with untrustworthy ownership are
  quarantined, never rebound to the current user.
- **Note:** if any affected build is live during transition, isolation ships
  before further release, ahead of the rest of retirement.

### Finding 2 — purchase/setup screens and activation codes are disconnected

- **Status:** open; not fixed.
- **Owning chunks:** 18, 19, 20; enterprise path also 23.
- **Story:** `US-37`, criteria `AC-37.2`–`AC-37.4`; enterprise in `US-40`.
- **Acceptance test:** a full journey test — signup → plan purchase *or*
  organization invitation/code redemption → provisioning → installation →
  Home/My Line — driven through production navigation, not a test-only route.
  Includes cold and warm launch from an activation link, expired code,
  already-used code, back navigation, and returning-user service recovery.
  Redemption binds to the intended recipient.

### Finding 3 — display refresh does not measure data consumption

- **Status:** open; not fixed.
- **Owning chunk:** 16; consumer presentation in 20.
- **Story:** `US-36`, criteria `AC-36.1`–`AC-36.3`.
- **Acceptance test:** real supplier usage ingestion reduces the displayed
  allowance, with persistent cursors, retry, deduplication by supplier event ID,
  a stale-reading indicator, and reconciliation of delayed, reordered and
  corrected readings without double debit. An initialized database balance or a
  screen refresh does not pass this test. Physical consumption evidence is
  chunk 29.

### Finding 4 — accepted order with a lost response can double-purchase

- **Status:** open; not fixed.
- **Owning chunks:** 11 and 15; bulk path also 23.
- **Story:** `US-32`, criteria `AC-32.4`–`AC-32.6`; carrier side `US-35`.
- **Acceptance test:** PostgreSQL-backed concurrency and crash tests — the
  operation reference and supplier attempt are persisted *before* dispatch;
  accepted / definitively-rejected / outcome-unknown are classified separately;
  an accepted-but-response-lost attempt reconciles against the original supplier
  using its documented idempotency and does **not** purchase a second profile,
  including after a worker restart mid-flight. No premature failover to another
  supplier after an unknown outcome. Applies with only Telnyx enabled.

### Finding 5 — API clock mismatch and iOS screenshot CI failures

- **Status:** **split.** The API clock failure is *currently reproducing*. The
  iOS screenshot failure is *intermittent* — it failed on 2026-09-07 and
  succeeded on 2026-09-08 on the same commit, validating 32 PNGs; the upload contains those images plus one XML report.
- **Owning chunk:** 02 for both; release proof in 27–29.
- **Story:** `US-42`, criteria `AC-42.1`–`AC-42.3`.
- **Acceptance test (API clock):** `tests/test_auth_api.py::test_otp_request_and_verify_contract`
  passes under one controlled test clock shared by token creation and JWT
  validation, with both a valid-token and an expired-token case, and **without**
  disabling production expiry checks.
- **Acceptance test (screenshots):** strengthen the existing count check into
  exact expected screen/locale coverage. The screenshot job asserts a complete,
  nonempty manifest for the revised screen/locale matrix and fails when an
  expected image is missing — flakiness must surface as a failure, not as a
  silently short manifest. The historical 0/32 and the observed 32 both describe
  the old matrix and neither carries forward; chunk 08 defines the new matrix
  and chunk 27 makes it a release gate.

## How to extend this map

When a chunk is split into lettered subchunks, add a row per subchunk and keep
the parent story. When a new story is genuinely needed, take the next free ID
after the highest registered in `prd.md` §10 — never reuse `US-01`–`US-26`.
