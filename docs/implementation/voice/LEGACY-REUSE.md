# Legacy voice code — reuse, refactor or reject

Reviewed **9 September 2026** against retained `apps/api/app/voice/` code and
the chunk 04D removal commit `390f792`. Never restore that commit wholesale.

## Reuse as a primitive

| # | Component | Path | Decision |
|---|---|---|---|
| R1 | Ed25519 verification | `apps/api/app/voice/service.py::_verify_signature` | Reuse signature and timestamp-freshness verification, then add a durable unique event inbox. Freshness alone is not replay deduplication |
| R2 | Call financial history | `apps/api/app/voice/models.py::CallLog` | Preserve existing records and identifiers; extend through additive migration for attempt/leg/usage settlement |
| R3 | Provider boundary concept | `apps/api/app/voice/providers.py::VoiceProvider` | Keep provider code outside routes and UI, but replace method contracts for explicit operations, returned identifiers and uncertain outcomes |
| R4 | Signature-first dispatch order | `apps/api/app/voice/service.py::process_webhook` | Keep authentication before parsing/state mutation; insert durable event-id dedup and authoritative leg lookup before dispatch |
| R5 | Contract-probe harness | `apps/api/tools/telnyx_probe/` | Extend with dated fixtures and account probes rather than creating another harness |

## Refactor before use

| # | Component | Path | Required change |
|---|---|---|---|
| F1 | Origination adapter | `providers.py::TelnyxVoiceProvider.initiate_call` | Remove verified-CLI fields, return all provider identifiers, accept a persisted operation id, expose unknown outcome, and implement only the selected topology |
| F2 | Bridge adapter | `providers.py::TelnyxVoiceProvider.bridge_call` | Current code sends `call_control_id`; official generated examples use `call_control_id_to_bridge_with` while other official schema/tutorial text still shows `call_control_id`. Confirm the accepted field in the probe before enabling |
| F3 | Voice credential | `models.py::VoiceCredential` | Replace unique-per-user ownership with one revocable credential per device/browser installation; record provider connection, expiry/revocation and owner scope |
| F4 | Credential creation/token issue | `providers.py::create_credential/issue_token` | Use per-device names/tags, a bounded parent expiry and server-issued short-lived client sessions; do not infer token expiry from local wall clock without provider response/claim validation |
| F5 | Hangup billing | `service.py::_handle_hangup` | Replace package-minute debit and single-leg assumptions with V03 usage ingestion and ledger settlement |
| F6 | Eligibility | `service.py::eligibility` | Replace active-package minutes with entitlement, tariff, payer and atomic reservation checks; internet calling cannot require an eSIM package |
| F7 | Nigeria normalization | `apps/api/app/voice/nigerian_numbers.py` | Reuse tested E.164 destination normalization only; do not use it as caller-identity verification |
| F8 | `client_state` decoder | `service.py::_client_state` | Keep as a parser after signature verification, but never authorize or settle from decoded values without authoritative database mapping |

## Reject for the new route

| # | Component | Where | Reason |
|---|---|---|---|
| X1 | Caller identity services/routes | removed by `390f792` | Customer-owned verified caller ID is deferred |
| X2 | Verified caller/consent domain as active eligibility | retained historical tables | Preserve required history/retention, but do not wire it into the new route |
| X3 | Existing `_handle_initiated` authorization behavior | `service.py` | It trusts the retired verified-CLI/client-dials model and lacks a single-use grant/event inbox |
| X4 | App-to-app calling | `service.py::_handle_app_to_app_hangup` | Outside outbound-to-PSTN scope |
| X5 | Incoming CallKit/PushKit bridge | removed mobile files | Incoming ringing is deferred; V04 evaluates active outbound-call integration independently |
| X6 | Retired CLI/voice endpoint clients | removed mobile files | Contracts no longer match |
| X7 | `IDTExpressVoiceProvider` stub | `providers.py` | No second voice provider is approved |

## Legacy assumptions that must not cross the boundary

1. **Package minutes.** Internet-only users may have no eSIM or Package. Voice
   authorization uses entitlements and the shared ledger.
2. **NGN-only money.** Telnyx supplier charges are in USD; payer, seller,
   customer tariff, settlement and FX versions remain explicit.
3. **Exactly one billable leg or exactly two CDRs.** Both are unproven for the
   chosen topology. Store every supplier component and charge customer talk time
   once.
4. **Shared session identifiers.** Independently created legs are associated by
   DamDam's attempt/leg records; provider session/CDR fields are supporting data.
5. **One credential per user.** Telnyx recommends separate device credentials;
   sharing one SIP identity across devices creates registration and revocation
   ambiguity.
6. **Verified customer number as caller ID.** Use only a provider-authorized
   assigned identity that has been proven for the route.

## Traceability

Current and removed paths can be checked with:

```bash
git show 390f792 -- apps/api/app/voice/caller_identity_service.py
git show 390f792 -- apps/mobile/src/services/callKit.ts
git log --diff-filter=D --name-only 390f792
```
