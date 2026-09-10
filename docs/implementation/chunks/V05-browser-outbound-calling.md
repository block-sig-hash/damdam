# Chunk V05 — Consumer browser calling

**Story:** US-48.
**Depends on accepted scope:** V03, 08 and browser authentication from 06/07.

## Outcome and scope

Implement an authenticated consumer calling area in the existing Next.js app,
separate from organization and internal admin routes/roles. Use V02/V03 backend
contracts and an SDK service wrapper. No duplicate calling engine or new wallet.

Offer keypad/manual international number entry, destination tariff and outbound
identity/payer preview, call status, mute, DTMF, hangup and backend-derived history.
Personal calling must work with no eSIM and no organization membership. Request
microphone permission at use; handle denial/no device, unsupported browser,
network failure, expired session and low funds without accidental paid retries.

Use HTTPS, the approved auth/CSRF/origin model, short-lived grants and restrictive
credential handling. Do not expose a Telnyx API key or unrestricted SIP password.
Handle duplicate tabs, tab close/refresh, browser sleep and reconnect using the
same durable attempt; reconcile active state instead of redialing. Unload callbacks
are best effort, never the spending-control mechanism. Clear scoped data on logout
and prevent delayed callbacks leaking across accounts. No incoming browser ringing.

## Acceptance — AC-48.1 to AC-48.3

Test personal/no-organization access and denied admin/cross-tenant access;
unauthorized origins, copied token abuse, duplicate tabs, session expiry and
browser closure cannot bypass server controls. Run dashboard tests/lint/types/
production build and rendered browser journey checks with English/French and
keyboard accessibility. Live supported-browser microphone/audio/DTMF/identity/
actual-charge proof is distinct from mocked browser tests and remains pending
if access is missing. V04/V05 cross-client spend tests belong to chunk28 as well.

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
