# Verified Caller ID Hardening — Scoping
# DamDam — Version 0.1 · Audit date: 24 July 2026

## 1. Decision summary

A detailed external spec proposed rebuilding US-14 ("outbound calls
showing the pilgrim's real Nigerian number") as a from-scratch MVP:
per-number CLI verification decoupled from login, NIN identity
verification, a CLI authorization state machine, an IDT Express SIP
adapter, wallet-style billing, and ~5 new mobile screens.

US-14 already shipped. This document audits what exists against
that proposal and separates it into three buckets:

1. **A real, worth-fixing gap:** CLI "verification" today is just
   the account's login OTP reused, with no separate ownership proof,
   no consent record, no state machine, and no revocation path. This
   is worth hardening.
2. **Already-decided, already-deferred:** IDT Express is documented
   in `prd.md` §5.5 as a Phase 2+ cost-optimization migration, not
   an MVP item. The proposal's full SIP-adapter treatment is correct
   *content* for when that phase starts, not now.
3. **Net-new product/legal scope:** NIN identity verification isn't
   in any DamDam spec today. Collecting a Nigerian national
   identifier is a legal/regulatory decision, not an engineering
   default — flagged for founder sign-off below, not assumed.

The recommendation in §5 below scopes an MVP that fixes (1), leaves
(2) exactly where it already was, and ships (3) behind a
default-off flag with no strict NIN-MSISDN matching until that
sign-off happens.

## 2. What exists today (verified against `develop`, not assumed)

**Architecture:** WebRTC click-to-call, not server-initiated REST
call creation. The mobile app registers a per-user Telnyx SIP
telephony credential (`VoiceCredential`), requests a short-lived
WebRTC token (`POST /voice/token`), and dials from the device SDK.
Telnyx's `call.initiated` webhook is the actual trust boundary: the
backend looks up the SIP credential owner from the inbound leg,
decides `app_to_app` (registered DamDam user, free, routed
client-to-client) vs `pstn` (external number), and — for PSTN —
issues the outbound Telnyx `/calls` request itself with `from` set
to the account's number, then bridges the two legs on
`call.answered`. **The mobile client never supplies a caller ID at
any layer** — the external spec's "Core security rule" is already
satisfied structurally, just not through explicit
verification/consent/state tracking.

- `apps/api/app/voice/models.py` — `VoiceCredential` (Telnyx SIP
  credential per user), `CallLog` (`telnyx_call_leg_id`,
  `call_type`, `to_number`, duration, `pstn_minutes_charged`,
  timestamps)
- `apps/api/app/voice/providers.py` — `VoiceProvider` protocol +
  `TelnyxVoiceProvider` (credential provisioning, token issuance,
  call initiation, bridging)
- `apps/api/app/voice/service.py` — eligibility, token issuance,
  webhook handling (`call.initiated`/`call.answered`/`call.hangup`),
  Ed25519 webhook signature verification, minute-based billing
  against the active `Package`
- `apps/api/app/voice/routes.py` — `GET /voice/eligibility`,
  `POST /voice/token`, `POST /webhooks/telnyx/call-events`,
  `GET /me/calls`
- `apps/api/app/voice/schemas.py` — `normalize_dialed_number`:
  already handles `0XXXXXXXXXX` and `+234XXXXXXXXXX`, strips
  spaces/hyphens/parens; does not yet handle bare `234XXXXXXXXXX`
  (no leading `+`), does not reject premium-rate/short-code ranges,
  and does no carrier lookup — pattern match only
- `apps/api/app/auth/models.py` — `User.verified_cli: bool`, default
  `False`
- `apps/api/app/otp/service.py:325` — `user.verified_cli = True` is
  set **inside the account-login OTP flow itself**, with an inline
  comment explicitly documenting this as deliberate: *"the
  account-setup OTP is the CLI ownership verification for Path A
  pilgrims, reusing this same login number with no separate
  verification step."*
- `docs/prd.md` §5.5 — the CLI/voice spec, `VoiceProvider`
  abstraction already framed as vendor-swap-ready; IDT Express
  explicitly scoped as **Phase 2+, cost-optimization only**, not a
  reliability or verification change; single-vendor risk (no
  automatic Telnyx failover) explicitly accepted at MVP because
  voice is not safety-critical
- `docs/api-spec.md` §7.5 — matches the service.py contract exactly
- `docs/testing-qa.md` §14.9 — `test_voice_api.py`,
  `test_voice_model_postgres.py`, `test_voice_providers.py`, native
  CallKit (iOS)/ConnectionService (Android) integration already
  built on top of this call flow

**Billing model:** minutes decremented from a `destination_country`-
scoped `Package.pstn_minutes_remaining`, not a money-denominated
wallet. There is no wallet/ledger abstraction anywhere in the voice
path.

## 3. Gap table

| Proposed requirement | Status | Notes |
|---|---|---|
| Backend, not client, controls caller ID | **Already true** | Structural, via the WebRTC+webhook trust boundary — no client `from`/`caller_id` field exists anywhere in the contract |
| CLI verification separate from login/2FA | **Missing** | `verified_cli` is the login OTP, full stop |
| CLI decoupled from the account's own number | **Missing** | Today's model is 1:1: the verified number *is* `user.phone_number`. A diaspora Nigerian logging in on a non-NG number, or a pilgrim wanting to verify a different NG line, cannot today |
| Consent record (versioned, revocable) | **Missing** | No consent table, no revocation endpoint |
| CLI authorization state machine | **Missing** | Just a boolean |
| Nigerian number normalization | **Partial** | Handles `0XX…`/`+234XX…`; misses bare `234XX…`; no premium-rate/short-code rejection |
| Carrier-lookup interface | **Deferred, not a gap this pass** | No carrier-lookup vendor is chosen anywhere in the doc suite; `detected_carrier` stays `NULL` until that vendor decision is made, same treatment as the other deferred items below |
| Fraud/rate limits specific to CLI verification | **Missing** | General auth rate-limiting exists (OTP), nothing CLI-specific |
| Telnyx webhook signature verification | **Already true** | Ed25519, timestamp-window, matches the proposal's requirement exactly |
| Webhook idempotency | **Already true** | Unique `telnyx_call_leg_id` insert is the idempotency boundary; duplicate `call.hangup` is a documented no-op |
| Billable-duration, once-only charging | **Already true** | Row-locked package read + single charge in `_handle_hangup` |
| NIN identity verification | **Missing, and not in any spec** | Zero prior mention in `prd.md`/`data-model.md`/`security.md` |
| IDT Express SIP adapter | **Deferred, on purpose** | `prd.md` §5.5 already scopes this to Phase 2+; not a gap, a sequencing question |
| Wallet-style reservation billing | **Different model exists** | Minutes-against-package, not money-against-wallet; not a gap so much as a modeling choice already made elsewhere in the product |
| Number-management screens (revoke/reverify/lost-SIM) | **Missing** | No such screens; nothing to revoke today since there's no separate CLI record |

## 4. Decisions this needs before implementation (not mine to make unilaterally)

**Action items flagged for founder/product review** (same framing as
the existing financial/SOS retention item in `security.md` §10.3):

1. **Is NIN identity verification actually required, and on what
   legal basis?** NIN is a Nigerian national identifier; collecting
   it is a KYC-grade decision with real regulatory exposure (NDPA),
   not a default an engineering pass should assume. Recommendation
   below ships the CLI-hardening work with `NIN_VERIFICATION_ENABLED`
   and `STRICT_NIN_MSISDN_MATCH_REQUIRED` both off, so nothing here
   is blocked on this answer — but the identity-provider adapter
   should stay a labeled mock until this is resolved.
2. **Should IDT Express move up from Phase 2+?** Nothing about the
   CLI-verification hardening requires it. Recommendation: leave it
   exactly where `prd.md` §5.5 already put it — a disabled,
   config-shaped stub in this pass, real SIP trunk work only once
   call volume actually justifies the wholesale-termination cost
   case that motivated it in the first place.
3. **Does per-number CLI verification replace or sit alongside the
   existing login-OTP-implies-CLI shortcut?** Recommendation:
   replace it — the shortcut is the actual security weakness here
   (a compromised or SIM-swapped login session inherits CLI rights
   with zero additional proof). Existing users' current
   `verified_cli=True` state should migrate to a `phone_verified`
   (not `active`) CLI record requiring one fresh consent capture,
   not a silent grandfathering to `active`.
4. **Which carrier-lookup vendor, if any, backs `detected_carrier`?**
   Not a legal question like NIN, but still an unresolved
   product/vendor decision — no such vendor is named anywhere in
   `prd.md`. Recommendation: leave `detected_carrier` `NULL` and
   unpopulated this pass rather than guessing a vendor or inferring
   carrier from number prefix (Nigerian numbers port between
   carriers, so a prefix-based guess would be actively misleading).

None of these block writing the spec text below — they block
*strict-mode* activation, which stays off by default either way.

## 5. Recommended MVP scope

**Build now:**
- `VerifiedCallerIdentity` + `CallerIdConsent` models, decoupled
  from `User.phone_number`
- CLI state machine (states below), replacing the `verified_cli`
  boolean
- Telnyx Verified Numbers as the phone-possession check, separate
  from login OTP, wired into the *existing* `VoiceProvider`
  abstraction rather than a new call-creation path
- Consent screen + revoke/reverify/lost-SIM management, extending
  the existing mobile calling flow rather than replacing it
- Extend `CallLog` in place with the CLI linkage, idempotency key,
  and failure/route metadata fields the proposal wanted on a new
  `CallRecord` — no second call-record table
- Nigerian number validation hardening (bare `234…` support,
  premium-rate/short-code rejection)
- Fraud/rate-limit controls scoped to CLI verification specifically,
  covering both issuing new codes (`start_verification`) and guessing
  an already-issued one (`confirm_verification`) — these are separate
  attack surfaces and need separate limits

**Stub, disabled by default:**
- NIN identity-verification adapter as a clearly labeled mock;
  `nin_msisdn_match_status` defaults to `unavailable`, never
  silently `matched`
- IDT Express adapter as an unreachable, config-validated stub
  (`cli_mode = unsupported`, `nigeria_cli_preservation_approved =
  false`) — exactly what `prd.md` §5.5 already committed to

**Deferred, not built this pass:**
- Carrier-lookup interface for `detected_carrier`. No carrier-lookup
  vendor is chosen anywhere in this doc suite, and picking one is a
  net-new vendor decision (same category as the OTP/voice/eSIM/payment
  choices `CLAUDE.md` already tracks explicitly) rather than a detail
  inside this CLI-hardening pass. `detected_carrier` stays a nullable
  column, always `NULL` until that vendor decision is made and a real
  adapter is wired in — never inferred from number prefix alone, since
  Nigerian numbers port between carriers.

**Not building:** a wallet/ledger rewrite of the existing minutes-
against-package billing; a route-policy/fallback layer beyond what
single-vendor-accepted-risk already implies; new REST call-creation
endpoints replacing the WebRTC+webhook flow.

## 6. Ownership

Per `CLAUDE.md`'s split, `apps/api/**` and non-exception
`apps/mobile` screens (calling, consent, number-management — none of
these are the named SOS/onboarding exception) are Codex's
implementation scope once this is approved, with Claude reviewing
the rendered mobile screens against `design-system.md` as usual.

See the accompanying amendments:
`docs/prd.md` §5.5 Amendment and `docs/data-model.md` §6.40.
