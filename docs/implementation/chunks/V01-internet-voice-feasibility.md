# Chunk V01 — Internet-voice feasibility and legacy reuse contract

**Story:** US-44.
**Depends on accepted scope:** 03 documented scope, 04, 05 and the approved calling amendment.

## Outcome

Produce a documented implementation contract for outbound Telnyx internet calls
from React Native and browser to ordinary phone numbers. This chunk changes
research/specifications only: no runtime code, SDK installation, schema or CI.
It can run alongside independent identity or staging work in separate worktrees.

Create `docs/implementation/voice/` containing `CAPABILITY-MATRIX.md`,
`API-CONTRACTS.md`, `COST-MODEL.md`, `LEGACY-REUSE.md`, `GO-NO-GO.md` and an
**unsent** `ENQUIRY-DRAFT.md`. Link them from the docs index and update the D1
internet track without modifying the accepted carrier evidence.

## Required investigation

1. Recheck dated official SDK/API sources. Choose and justify the minimum route
   topology: client media leg, backend authorization/control, PSTN leg and CDRs.
   Map documented endpoints/events, signature validation, credential lifetimes,
   idempotency/correlation, answered/ended semantics and termination behavior.
   Do not invent per-destination JWT claims or a nonexistent server veto hook.
2. Establish how a copied SDK credential cannot originate unauthorized billable
   calls. Document provider-enforced routing, approved destinations/identity,
   concurrency and duration controls; distinguish API guarantees from desired
   behavior and account-specific questions. Missing enforcement blocks a live
   route, not honest preparatory documentation.
3. Separate internet and carrier capabilities, outbound identity ownership,
   same-number reuse, callback/inbound policy, resale/market restrictions and
   emergency calling. WebRTC sources do not prove carrier coverage. Caller ID
   must not depend on the retired third-party verification flow.
4. Build a cost worksheet with symbolic inputs unless rates are evidenced:
   Nigeria mobile/landline destinations, origination/PSTN/platform legs, minimums,
   increments, connection fees, number rental, taxes, FX and termination-delay
   exposure. Distinguish supplier cost from retail tariff and prepaid headroom.
   No claim of cheaper calls without comparable verified inputs.
5. Review retained `apps/api/app/voice/` and the chunk04 diff/history. Inventory
   old credential, webhook, billing, mobile SDK/native bridge, permission and test
   code as reusable/refactor/reject, with current or historical paths and reasons.
   Check account ownership, HTO/minutes/NGN assumptions and verified-CLI coupling.
6. Record SDK compatibility with the actual React Native/iOS/Android versions,
   supported browsers, WebRTC media/connectivity needs and outbound foreground/
   background/lock-screen behavior. Incoming push is deferred; identify any
   outbound native integration requirements independently. Do not change hosting
   firewalls or reinstall PushKit/FCM because an old sample used them.

## Acceptance — AC-44.1 to AC-44.4

- Every relevant capability/contract is marked documented, account-confirmed,
  physically tested, unsupported or unknown, with date/source/evidence.
- One explicit route/control design maps to evidence and unresolved questions;
  account access, all-leg cost and bounded stopping are not assumed.
- A reviewer can trace every proposed reused component to current or historical
  code and understand why it fits or fails the new scope.
- GO-NO-GO distinguishes documented preparation from live production readiness
  and gives V02 a concrete interface proposal, negative test matrix and blockers.
  If docs cannot resolve the topology, mark that portion EXTERNAL_BLOCKED rather
  than inventing a production contract. V02 may only implement evidenced parts.

Validation: run docs link validation and `git diff --check`; verify source links
and inventory paths/SHAs. No application suite is required for docs-only work.
Do not label future V02 contracts as implemented endpoints.

## Working and handoff rules

Read AGENTS.md, the docs index, [the calling amendment](../VOICE-EXPANSION.md),
PRD §11, DECISIONS.md and the accepted dependency reviews. Inspect current
branches/worktrees; use an isolated branch from accepted code and preserve
unrelated work. Do not implement missing prerequisites. Claude implements;
Codex independently reviews/refactors. Do not mark your own work accepted.

Use internal provider/service boundaries, numbered data-model amendments and
synchronized API contracts. Never restore chunk 04 wholesale. Keep historical
financial data and the quantity-one order-item invariant. Follow strict TDD for
authorization, idempotency, money and concurrency; use PostgreSQL for backend
behavior. Run affected repository checks and meaningful failure tests. Report
unrun checks and external limitations explicitly; a mock is not live evidence.

No vendor message, paid call/purchase, deployment, merge, store submission or
production deletion is authorized by this assignment. Prepare unsent enquiries;
use existing authorized sandbox access only. Keep credentials out of logs/docs.
Return [HANDOFF-TEMPLATE.md](../HANDOFF-TEMPLATE.md) at `handoffs/VNN.md` (use this
chunk's ID), record exact base/head SHAs and status, and stop for Codex review.
