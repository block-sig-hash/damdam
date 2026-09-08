# Implementation status

Chunk 01 (documentation reset) is implemented and awaiting independent Codex
review. No application chunk has been implemented. Nothing here is accepted.

**Base for all current work:** `develop` @
`6790c74707a0f3e52cfedb36bc173ec83ca26663`, confirmed current on 2026-09-08 —
see [BASELINE.md](BASELINE.md).

| Chunk | Status | Base/head SHA | Review record | Remaining gate |
|---|---|---|---|---|
| 01 — Reset product specifications and working rules | READY_FOR_REVIEW | base `6790c74` / head see [handoffs/01.md](handoffs/01.md) | pending | None blocking chunk 01; D1–D6 recorded OPEN |
| 02 — Repair the CI baseline and screenshot harness | NOT_STARTED | — | — | See assignment |
| 03 — Prove Telnyx feasibility and document the carrier contract | NOT_STARTED | — | — | See assignment |
| 04 — Retire family, safety and app-calling features safely | NOT_STARTED | — | — | See assignment |
| 05 — Introduce core domain models and migration boundaries | NOT_STARTED | — | — | See assignment |
| 06 — Implement global identity and account recovery | NOT_STARTED | — | — | See assignment |
| 07 — Implement memberships, tenant isolation and administrator MFA | NOT_STARTED | — | — | See assignment |
| 08 — Define the consumer and enterprise design system | NOT_STARTED | — | — | See assignment |
| 09 — Build supported-market catalog and immutable quotes | NOT_STARTED | — | — | See assignment |
| 10 — Build the multi-currency ledger and atomic reservations | NOT_STARTED | — | — | See assignment |
| 11 — Build order orchestration and durable recovery | NOT_STARTED | — | — | See assignment |
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

## Legacy release compatibility boundary

`scripts/validate-release-signoff.sh` and `docs/release-signoffs/TEMPLATE.md`
still require "Offline check-in survival" and "Offline SOS survival" rows in
every release signoff, for features the reset schedules for retirement. The
workflow still expects these rows. Current server-side branch protection was
not verified; see [BASELINE.md](BASELINE.md).

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

## Updating this record

Claude may record IN_PROGRESS, READY_FOR_REVIEW, EXTERNAL_BLOCKED and handoff links. Only an independent Codex review records ACCEPTED or CHANGES_REQUIRED. Acceptance identifies the reviewed/tested code. Explicitly list lettered subchunks and their unaccepted remainder where work was split.

A review record can be carried forward only if the relevant code/configuration has not changed; subsequent changes require appropriate revalidation. Store approval/status text separately from executable runtime configuration.
