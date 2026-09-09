# Chunk V04 — Mobile outbound internet calling

**Story:** US-47.
**Depends on accepted scope:** V03, 08, 18.

## Outcome and scope

Add Calls to production mobile navigation and integrate a supported Telnyx SDK
behind a mobile service wrapper. Reuse reviewed components selectively.

Provide keypad/manual international number entry, rate/identity/personal-work
payer preview, permission request at first internet call, connecting/ringing/
answered/ended/failed states, elapsed-time estimate, mute, audio route, DTMF,
hangup and backend-derived cost/history. An internet-only customer needs no eSIM.
Label native-carrier and internet actions explicitly; native SIM selection cannot
be inferred or forced by changing the app payer. No in-call handover promise.

Handle microphone denial, session expiry, offline network, low funds, revoked
membership, duplicate taps, app switch/lock, interruption by a cellular call and
network change. Confirm supported behavior per OS/SDK; disclose any lifecycle
limitation and never leave an untracked billable call. Server/provider cutoff
continues if the client dies. Incoming PushKit/FCM/ringing remains out of scope;
add outbound native integration only where required and evidenced.

## Acceptance — AC-47.1 to AC-47.3

A production navigation test covers signup/eligible grant → rate preview → call
→ history without installation. Account switch and delayed SDK callbacks cannot
show or control the previous user's call. Native builds, Jest/lint/types,
English/French/accessibility and derived screenshot matrix checks apply. Prove
real iOS/Android outbound audio, DTMF, identity, interruptions and cost when
access is authorized; keep unavailable device/live evidence explicitly pending.
No restored SOS/contacts/location collection or third-party CLI gate is permitted.

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
