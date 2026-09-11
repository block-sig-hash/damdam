# DamDam — Agent Instructions

Read [`/docs/README.md`](./docs/README.md) first for the full spec index and
recommended reading order, then
[`/docs/implementation/README.md`](./docs/implementation/README.md) for the
current build sequence. All product, technical, security and infrastructure
decisions live in `/docs` — treat it as the source of truth, not this file.

**This file was rewritten by chunk 01 on 8 September 2026**, at the user's
explicit request, to record a new working split and a reset product scope. The
previous "Claude designs, Codex implements, Claude reviews" ownership table and
the pilot feature freeze are superseded. See
[`/docs/implementation/`](./docs/implementation/) for the reset itself.

## The product, in one paragraph

DamDam serves consumers and enterprise/government organizations with eSIM data,
carrier native-dialer voice where proven, and outbound internet calling from the
mobile app and customer website. Internet calling can be bought without an eSIM.
Telnyx remains preferred, subject to separate evidence for each calling mode.
Read [the approved calling amendment](./docs/implementation/VOICE-EXPANSION.md)
and PRD §11 before implementing. Incoming app/browser ringing, external verified
caller ID and porting remain deferred. Family contacts, SOS and pilgrimage
framing stay retired. Every public service claim requires supporting evidence.

## Who implements what

**Claude implements. Codex independently reviews and may refactor.**

That is the whole rule. It is not subdivided by area, language or screen —
Claude writes the API, the mobile app, the dashboard, the infrastructure and the
tests; Codex reviews all of it with authority to fix and refactor within scope.

| Role | Responsibility |
|---|---|
| **Claude** | Implements one chunk at a time on an isolated branch. Runs the affected required checks. Returns [`docs/implementation/HANDOFF-TEMPLATE.md`](./docs/implementation/HANDOFF-TEMPLATE.md). **Never marks its own work accepted.** |
| **Codex** | Independently reviews the actual diff and its integration points, verifies behavior and failure cases, fixes and refactors defects within scope, adds regression coverage, and records ACCEPTED / CHANGES_REQUIRED / EXTERNAL_BLOCKED against a named head SHA in `docs/implementation/reviews/NN.md`. |

The cycle, per chunk:

1. Claude implements chunk `NN` from `docs/implementation/chunks/NN-*.md` on a
   dedicated branch cut from the last accepted code, preserving unrelated work.
2. Claude records the handoff at `docs/implementation/handoffs/NN.md` and sets
   the chunk to `READY_FOR_REVIEW` in `docs/implementation/STATUS.md`.
3. Codex reviews using `docs/implementation/REVIEW.md`, fixes what needs fixing,
   and records the review and status.
4. Only after acceptance does the next dependent chunk start. Carry Codex's
   fixes forward into the next branch.

Keep **one active implementation chunk** by default. Do not start the next chunk
because the current one "looks done". Do not merge, deploy, submit to a store,
send a vendor message, make a live purchase or delete production data as part of
any chunk unless separately authorized.

## Before implementing any chunk

1. Read the chunk file in [`/docs/implementation/chunks/`](./docs/implementation/chunks/)
   in full — it is a complete assignment, including its acceptance criteria.
2. Find its registered story in [`/docs/prd.md`](./docs/prd.md) §10 and §11 via
   [`/docs/implementation/STORY-MAP.md`](./docs/implementation/STORY-MAP.md),
   and read the acceptance criteria.
3. Read the accepted dependency reviews in `docs/implementation/reviews/`. Do
   not build on an unaccepted chunk, and do not silently absorb a missing
   predecessor's work.
4. Check [`/docs/implementation/DECISIONS.md`](./docs/implementation/DECISIONS.md)
   for the D1–D6 gates your chunk depends on. A gate does not stop preparatory
   work; it stops you calling gated scope complete.
5. Cross-check `/docs/data-model.md`, `/docs/api-spec.md`, `/docs/security.md`
   and the frontend spec for your platform.
6. Check [`/docs/implementation/SCOPE-DISPOSITION.md`](./docs/implementation/SCOPE-DISPOSITION.md)
   before acting on any spec text that mentions Hajj, pilgrims, family contacts,
   SOS, check-ins, WebRTC calling, verified caller ID or HTOs. Those specs have
   not been rewritten yet; that file says which references are retired,
   generalized, deferred or purely historical.

## Test policy

Strict TDD — write the failing test first — is required for:

| Category | Why |
|---|---|
| Authentication, sessions, recovery | Edge-case-heavy; a lockout or expiry off-by-one is not caught by manual testing |
| Payments and idempotency | Double-charging or double-provisioning is trust-destroying and hardest to unwind at exactly the wrong moment |
| Tenant isolation and object-level authorization | A cross-tenant read is a breach, not a bug |
| Order and provisioning idempotency, including accepted-but-response-lost | The single most expensive failure mode in this product |
| Safety-transition tests during feature retirement | Retirement must not orphan queued work or rebind it to the wrong account |
| Ledger entry correctness and concurrency | Posted entries and reservations must remain correct under replay and concurrent requests |

Everywhere else: tests are required, TDD is recommended, and neither is
mechanically enforced by tooling — it is a review-time check.

Non-negotiable:

- **Use PostgreSQL for backend database and concurrency behavior.** Do not
  substitute SQLite for server constraints, locking or isolation. Mobile outbox
  persistence uses SQLite; test that actual storage and its restart behavior as
  well as the backend when validating safety retirement.
- **Keep existing safety tests while their paths are supported.** The applicable
  strict-TDD and full offline/chaos checks in `testing-qa.md` §14.4 remain required
  for retained or transitioning queues, retries and notification dispatch. Retire
  a scenario only with evidence that its path and supported old clients/jobs
  have been retired; account isolation is an additional requirement.
- **Never disable a check, lower a coverage threshold, or weaken a production
  expiry/authorization rule to make a test pass.** Fix the code or the test.
- **A mock passing itself is not evidence of external compatibility.** Vendor
  behavior claims need documented contract checks against current official
  documentation, with the date recorded.
- **Do not add tests that mirror the implementation** or chase a coverage
  number. A regression test should fail against the actual defect.

Run the affected required checks for your chunk. Do not re-run unrelated suites
endlessly after they pass. The complete integrated matrix runs in chunk 28.

## Build & test commands

```
# API (FastAPI) — PostgreSQL required
cd apps/api && pytest --cov=app
cd apps/api && ruff check . && mypy app

# Mobile (React Native, iOS + Android)
cd apps/mobile && npm test -- --runInBand
cd apps/mobile && npm run lint && npm run type-check

# Dashboard (Next.js)
cd apps/dashboard && npm test
cd apps/dashboard && npm run lint && npm run type-check && npm run build

# Full local stack
docker compose up
```

OpenAPI drift, migration and screenshot checks run in CI as configured; see
`.github/workflows/ci.yml`. Chunk 02 owns re-establishing the current CI
baseline — see `docs/implementation/BASELINE.md` for what is failing today and
what is only historically reported.

## Non-negotiable conventions

- Every chunk's PR or branch references its registered story ID (`US-XX`) and
  its chunk number.
- **Data model changes require a numbered amendment** in `data-model.md` (see
  §6.4/§6.5 for the pattern), never a silent edit.
- **API changes must keep `api-spec.md` in sync** — CI fails on drift between
  the committed spec and FastAPI's generated OpenAPI output.
- **All third-party vendor integrations go through an internal abstraction
  layer**, never called directly from route handlers or UI components. Client SDK
  media/signaling uses service wrappers; backend secrets and policy stay server-side. Each
  adapter advertises its capabilities (native voice, supported numbers, top-up,
  reuse, suspension, usage latency, spending enforcement); a data-only adapter
  cannot satisfy a native-voice plan. The boundary limits supplier-specific
  changes; a switch can still need a new adapter, profile, customer installation
  and commercial approval. It is not necessarily a configuration-only change.
- **An unknown supplier outcome reconciles against the original operation
  reference.** It never triggers a second purchase and never fails over to
  another vendor.
- **Money carries an explicit ISO currency and correctly scaled amounts.** Exact
  decimal precision for rates and metered usage, documented rounding, no
  cross-currency balance addition. Historical NGN records are preserved through
  every migration, including receipts and refunds.
- **Payment, provisioning, installation, activation and connectivity are
  separate states.** A paid order may be pending provisioning; installation does
  not prove network attachment.
- **Removal work follows the migration sequence** in
  `docs/implementation/IMPLEMENTATION-PLAN.md` §7 Phase 1: inventory deployed
  data → stop new enrollment and dispatch → handle queued work and old clients →
  backfill → verify migration and rollback → delete sensitive records per the
  approved retention policy → drop schema only after compatibility ends. Never
  erase order or audit history because a screen was removed.
- Secrets, credentials and eSIM activation material stay out of code, logs,
  test fixtures, handoffs and review records.

## Product boundaries — do not exceed without a recorded decision

Additional carrier integrations, recurring subscriptions, SSO/SCIM, MDM
deployment, a reseller marketplace, PBX/SIP features, AI features, multi-region
deployment and a microservice rewrite are all **out of scope**. Modular code
does not mean a plugin marketplace.

The selling legal entity (D3) and the global payment processor (D4) are
**unresolved decisions, not assumptions**. Do not write Stripe-specific code, or
hardcode an entity or a tax treatment, before
`docs/implementation/DECISIONS.md` records the selection.

Do not invent API endpoints, live prices, coverage claims, regulatory approvals
or successful test evidence. If a chunk needs an answer that only the founder or
a vendor can give, finish the independent work, name the exact missing input and
its owner in the handoff, and leave the remainder explicitly open.

## Cost and session discipline

Claude Code runs on direct Anthropic API billing for this project, so scope
sessions deliberately:

- Keep a session to one chunk. A sprawling session touching many unrelated files
  costs more and reviews worse.
- Let file-read tools pull `/docs` content directly rather than pasting large
  spec sections into a prompt — repeated reads of stable files benefit from
  prompt caching.
- If a chunk needs multiple independent migrations or features, propose lettered
  subchunks rather than delivering an unreviewable diff.

There is no automated model-review gate. It was quota-sensitive and duplicated
the independent Codex review without adding deterministic evidence. Only the
review record in `docs/implementation/reviews/NN.md` records acceptance.

## What NOT to do

- Don't add an API endpoint without adding it to `api-spec.md` first.
- Don't add a dependency without checking `aarch64` wheel/binary availability if
  it reaches the OCI Ampere A1 instance (`scaling-infrastructure.md` §12.2).
- Don't touch `.env.production` or anything under `/apps/api/secrets/`.
- Don't mark a PR or a chunk ready for review without running its linked checks.
- Don't mark your own work accepted, and don't start the next chunk. Codex
  reviews first.
- Don't treat a passing sandbox implementation as merchant approval, VoLTE
  production support, real handset behavior or a compliant selling market.
- Don't repeat a historical CI or test result as a current fact. Re-run it, or
  label it historical.

## Commit convention

Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`) — see root
[`README.md`](./README.md) for branch strategy.
