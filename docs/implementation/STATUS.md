# Implementation status

Chunks 01, 02, 04, 05, 06, 07, 08 and chunk 03's documented/simulated scope are
**ACCEPTED after independent Codex review and fixes**.
Chunk 01 merged in [PR #100](https://github.com/block-sig-hash/damdam/pull/100).
Chunk 02's tested content and native evidence are recorded in
[reviews/02.md](reviews/02.md); [PR #101](https://github.com/block-sig-hash/damdam/pull/101)
carries its integration. Chunk 03 merged in
[PR #102](https://github.com/block-sig-hash/damdam/pull/102), and chunk 04 merged
in [PR #104](https://github.com/block-sig-hash/damdam/pull/104). The staging
bootstrap landed in PR #106 and was observed healthy through its CI deployment
before this review; each later merge requires its own deployment check. No
production-readiness claim is made.

**Original baseline:** `develop` @
`6790c74707a0f3e52cfedb36bc173ec83ca26663`, confirmed current on 2026-09-08 —
see [BASELINE.md](BASELINE.md).

**Chunk 04 is accepted after review fixes**, delivered as five subchunks on
`chunk/04-safe-feature-retirement`, based on `12582f1`. It withdraws behavior
and removes surface; it deletes no row, drops no table and adds no migration.
The retention plan in [retirement/RETENTION-PLAN.md](retirement/RETENTION-PLAN.md)
is a dry run that executes nothing.

**Current reviewed chunk 02 content:**
`4e5ecc9a55b4230c1b73923eff08fbf41b7f64bf`, based on accepted chunk 01 tip
`178c448d503eb2c5733c2daa7e12ce65159be769`.

| Chunk | Status | Base/head SHA | Review record | Remaining gate |
|---|---|---|---|---|
| 01 — Reset product specifications and working rules | ACCEPTED | base `6790c74` / corrected content `36e9bf36a2827d108633730ff0899edbd17b97ef` | [Independent review](reviews/01.md) | None blocking chunk 01; D1–D6 remain OPEN |
| 02 — Repair the CI baseline and screenshot harness | ACCEPTED | base `178c448` / corrected content `4e5ecc9` / CI head `aeb74f6` | [Independent review](reviews/02.md) | None blocking chunk 02; staging configuration remains D6/chunk 26 |
| 03 — Prove Telnyx feasibility and document the carrier contract | ACCEPTED (documented/simulated scope); live scope EXTERNAL_BLOCKED | base `178c448` / submitted `fe569e1` / corrected code `6a24c19` | [Independent review](reviews/03.md) | **D1/D2 OPEN** — no Telnyx account, live call, rate deck or cleared market |
| 04 — Retire family, safety and app-calling features safely | ACCEPTED after fixes (04A–04E), merged in PR #104 as `3fb2385` | base `12582f1` / submitted complete head `55394f5` / corrected app `d53c055` + native `6cf900a`, `e89d725` / CI head `0d4fee4` | [Independent review](reviews/04.md) | Check-in/welfare data disposition remains open; no welfare data deleted |
| 05 — Introduce core domain models and migration boundaries | ACCEPTED after fixes; integrated on accepted chunk 04 | base `12582f1` / submitted `87baa40` / corrected code `07dc308` / integration `4c82ed9` / final invariant `2109aef` | [Independent review](reviews/05.md) | D3 remains OPEN — `legal_entities` is deliberately unseeded |
| 06 — Implement global identity and account recovery | **ACCEPTED after fixes** (backend, migration and shared-device boundary) | base `d2f5349` / submitted `c07054e` / corrected `1ac8959` / integration `162d711` | [Independent review](reviews/06.md) | Live email delivery and mobile email screens remain gated to provider setup and chunks 18/21 |
| 07 — Implement memberships, tenant isolation and administrator MFA | **ACCEPTED after fixes** | base `c07054e` / submitted `01e9d93` / integrated with accepted chunk 06 at `a9137e9` | [Independent review](reviews/07.md) | MFA secret-at-rest encryption remains assigned to chunk 26; shared organization login retirement remains assigned to the dashboard migration |
| 08 — Define the consumer and enterprise design system | **ACCEPTED after fixes** | base `99bee92` / submitted `5e341fb` / corrected design code `6b9ca37` plus the final review-head native repository guard, integrated with chunks 06–07 | [Independent review](reviews/08.md) | iOS remains nightly/manual; product screens remain assigned to chunks 18–24 |
| 09 — Build supported-market catalog and immutable quotes | **ACCEPTED after fixes** | accepted base `8651aa9` / submitted `8286d5e` / corrected `3427e16` | [Independent review](reviews/09.md) | D2/D3 keep every market unpublishable; nothing is seeded |
| 10 — Build the multi-currency ledger and atomic reservations | **ACCEPTED after fixes** | submitted `1a19878` / rebased `bef1f67` / corrected `e9b10d8` | [Independent review](reviews/10.md) | Backfill not run against production-shaped data; no reservation-expiry sweeper pending D5 |
| 11 — Build order orchestration and durable recovery | **ACCEPTED after fixes (durable domain); runtime dispatch EXTERNAL_BLOCKED** | submitted `d232935` / rebased `4b82378` / corrected `8625daa` | [Independent review](reviews/11.md) | No worker runner wired; no real SupplierClient — a Telnyx adapter needs D1/V01 |
| 12 — Implement payment routing and modernize Paystack | NOT_STARTED | — | — | See assignment |
| 13 — Implement the selected global payment adapter and wallet checkout | NOT_STARTED | — | — | See assignment |
| 14 — Implement refunds, disputes, bank funding and receipts | NOT_STARTED | — | — | See assignment |
| 15 — Implement the Telnyx eSIM, line and number lifecycle | NOT_STARTED | — | — | See assignment |
| 16 — Implement actual usage reconciliation and carrier charging | NOT_STARTED | — | — | See assignment |
| 17 — Implement top-ups, spending controls and suspension | NOT_STARTED | — | — | See assignment |
| 18 — Connect mobile navigation, onboarding and redemption | NOT_STARTED | — | — | See assignment |
| 19 — Build the complete consumer purchase journey | NOT_STARTED | — | — | See assignment |
| 20 — Build My Line, eSIM installation and native-call guidance | NOT_STARTED | — | — | See assignment |
| 21 — Complete account, receipts, support and deletion | NOT_STARTED | — | — | See assignment |
| 22 — Build enterprise people, teams and validated imports | NOT_STARTED | — | — | See assignment |
| 23 — Build bulk orders, assignment and activation requests | NOT_STARTED | — | — | See assignment |
| 24 — Build enterprise funding, budgets, reports and offboarding | NOT_STARTED | — | — | See assignment |
| 25 — Build internal support and exception operations | NOT_STARTED | — | — | See assignment |
| 26 — Harden environments, backups and operational visibility | NOT_STARTED | — | — | See assignment |
| 27 — Update signed builds, privacy disclosures and release automation | NOT_STARTED | — | — | See assignment |
| 28 — Prove integrated flows, migrations and failure recovery | NOT_STARTED | — | — | See assignment |
| 29 — Run the authorized physical-device and enterprise pilot | NOT_STARTED | — | — | See assignment |
| 30 — Close release findings and prepare the production handoff | NOT_STARTED | — | — | See assignment |

## Legacy release compatibility boundary — closed by chunk 04E

`scripts/validate-release-signoff.sh` and `docs/release-signoffs/TEMPLATE.md`
required "Offline check-in survival" and "Offline SOS survival" rows, plus six
incoming-call/CallKit/PushKit rows. **Chunk 04 retired every feature all eight
tested**, so a truthful signoff could never satisfy them again and
[SCOPE-DISPOSITION.md](SCOPE-DISPOSITION.md) forbids fabricating retired-feature
evidence to pass the gate.

04E removed all eight from both files. It did **not** replace them with an empty
loop that silently passes: until chunk 27 re-cuts the release gates, the
scenario check fails loudly and names chunk 27 as the owner. Every other check
in that script — signoff artifact, tester, date and staleness, device matrix,
HTO usability — is untouched. Promotion to `main` is therefore blocked until
chunk 27, which is the intended state, not a side effect.

Current server-side branch protection was not verified; see
[BASELINE.md](BASELINE.md).

Chunk 01 deliberately left this alone — release automation is **chunk 27**'s
scope. AC-42.5 requires updating template and validator together, retaining
relevant protection and adding rejection tests. The reset product cannot use
the old matrix as release certification or invent evidence to pass it. This
boundary does not prevent reviewed implementation branches or chunk 02.

## External decisions

D1–D6 are recorded in [DECISIONS.md](DECISIONS.md) with owners, required
evidence and affected chunks. All six are **OPEN**. The proposed defaults
recorded there — welfare removal, email-based recovery, a new assigned number,
prepaid charging — are proposals from the plan awaiting the founder, not
approvals.

D1–D6 begin **OPEN / verify current evidence**. Do not infer they are closed from a prior conversation or a passing mock. Record owner, decision, supporting artifact/date, and impact on each affected chunk.

## Chunk 07 was started before chunk 06 was accepted

`AGENTS.md` says the next dependent chunk starts only after acceptance. Chunk 07
did not wait, at the user's instruction, and this is the record of that.

- Chunk 07 is branched from `c07054e` — chunk 06's **submitted** head, with no
  review record in `reviews/`. `reviews/06.md` does not exist.
- Independent review of chunk 06 was **in progress** while chunk 07 was written,
  in a separate worktree and database. Its in-flight fixes — a nullable
  `users.phone_number`, `users.auth_version` and access-token identity binding,
  an `AUTHENTICATE` token purpose, and a first-class email login — are **not in
  this branch**.
- Chunk 07 therefore contains **no** absorbed chunk 06 work, and nothing in it
  depends on those fixes. Where the two overlap, chunk 07 avoided the collision
  rather than duplicating it: the controlled migration creates no user account,
  which is why it needs no nullable `phone_number`; and the second factor is
  gated on a database row rather than a token claim, which is why it needs no
  `auth_version`.

**Chunk 06's accepted fixes must be carried forward into chunk 07's branch
before chunk 07 is merged**, and chunk 07's review should confirm the two
revocation mechanisms — `auth_version` for sessions, `organization_elevations`
for step-up — converge rather than sit side by side.

## Updating this record

Claude may record IN_PROGRESS, READY_FOR_REVIEW, EXTERNAL_BLOCKED and handoff links. Only an independent Codex review records ACCEPTED or CHANGES_REQUIRED. Acceptance identifies the reviewed/tested code. Explicitly list lettered subchunks and their unaccepted remainder where work was split.

A review record can be carried forward only if the relevant code/configuration has not changed; subsequent changes require appropriate revalidation. Store approval/status text separately from executable runtime configuration.

## Calling expansion approved — 9 September 2026

The founder approved [VOICE-EXPANSION.md](VOICE-EXPANSION.md). This adds work;
it does not reverse chunk 04 acceptance or imply restored calling code.

| Chunk | Story | Status | Remaining gate |
|---|---|---|---|
| V01 — Internet-voice feasibility | US-44 | **ACCEPTED AFTER FIXES** (documented/preparatory scope); live route **EXTERNAL_BLOCKED** | corrected content `90f6a4c` / [review](reviews/V01.md), [handoff](handoffs/V01.md), [evidence](voice/) — Park Outbound Calls is the documented preparation route; emergency bypass, containment, bounds, billing and live client proof remain B1–B5 |
| V02 — Outbound call control | US-45 | NOT_STARTED | Accepted V01 contract and 06/07/09/10/11; live controls gated |
| V03 — Internet charging | US-46 | NOT_STARTED | V02/10/14; provider cutoff, rates and D5 |
| V04 — Mobile outbound | US-47 | NOT_STARTED | V03/08/18; device/SDK and live evidence |
| V05 — Browser outbound | US-48 | NOT_STARTED | V03/08 and 06/07 browser auth; browser/live evidence |

Staging statements earlier in this file are the recorded chunk05 baseline, not
a fresh host/deployment assessment. Staging work is occurring separately; this
calling-plan change does not certify its completion or alter that checkout.
