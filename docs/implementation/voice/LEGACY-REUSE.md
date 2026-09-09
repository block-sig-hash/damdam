# Legacy voice code — reuse, refactor or reject

Produced by chunk V01 on **9 September 2026**, against
`d95db83c79239e495854ffb404709b7415a5e868` (planning tip, carrying accepted
application base `7aeea65`).

Two sources: the **retained** `apps/api/app/voice/` module, and code **removed
by chunk 04D** (`390f792`, "remove app calling and caller-ID verification"),
recoverable from history.

The governing rule from the assignment: *never restore chunk 04 wholesale.* Each
item below is judged against the **new** scope — outbound internet calling, no
eSIM requirement, no verified caller ID, no incoming ringing.

## REUSE — take substantially as-is

| # | Component | Path | Why it fits |
|---|---|---|---|
| **R1** | `VoiceService._verify_signature` | `apps/api/app/voice/service.py:368` | Ed25519 verification of `telnyx-signature-ed25519` over `timestamp \| payload`, plus a clock-tolerance window against replay. Matches current Telnyx documentation exactly. Written against a real contract and already covered by tests. **The single most valuable retained asset.** |
| **R2** | `CallLog` | `apps/api/app/voice/models.py:257` | Per-call financial/audit record. Chunk 04D explicitly retained it as financial history. Needs new columns (V02/V03), not replacement |
| **R3** | `VoiceProvider` Protocol | `apps/api/app/voice/providers.py:28` | The provider-boundary shape — `initiate_call`, `bridge_call`, `issue_token`, `create_credential` — is the right seam and keeps SDK/provider concerns out of routes. The Protocol survives even though its implementation changes |
| **R4** | Webhook→service routing | `apps/api/app/voice/service.py:89` `process_webhook` | Signature-first, then dispatch by `event_type`. Correct order; keep it |
| **R5** | Contract-probe harness | `apps/api/tools/telnyx_probe/` | Chunk 03's pattern for asserting fixtures against documented contracts without an account. V02 should extend it rather than invent a second approach |

## REFACTOR — the shape is right, the coupling is wrong

| # | Component | Path | What must change |
|---|---|---|---|
| **F1** | `TelnyxVoiceProvider.initiate_call` | `providers.py:89` | Currently takes `verified_caller_identity_id` and a `caller_id` from the retired CLI flow. Outbound identity becomes an **owned Telnyx number**; the CLI parameter goes |
| **F2** | `VoiceCredential` | `models.py:234` | One SIP credential per user is reusable, but it must be issued against a connection that **cannot dial PSTN** (API-CONTRACTS §5). Today nothing constrains what the credential may call |
| **F3** | `_handle_hangup` billing | `service.py:210` | Deducts `pstn_minutes_remaining` from a `Package` — the retired minutes-bundle model, and it charges a **single** leg. V03 replaces this with ledger settlement over **two** correlated CDRs. The duration/rounding logic is a useful reference, the money model is not |
| **F4** | `eligibility` | `service.py:50` | The `cli_not_verified` gate was already removed by 04D. What remains — a balance check before permitting a call — is the right idea, but it must consult the reservation/ledger, not `Package.pstn_minutes_remaining` |
| **F5** | `nigerian_numbers.py` | `apps/api/app/voice/nigerian_numbers.py` | Nigeria-specific normalisation. Useful for validating Nigerian **destinations**, which is still the target market; must not be reused as *identity* validation, which was its CLI purpose |

## REJECT — do not carry forward

| # | Component | Where | Why |
|---|---|---|---|
| **X1** | `caller_identity_service.py`, `verified_numbers.py` | deleted in `390f792` | Third-party verified caller ID. **Deferred under D2** and explicitly out of scope. Reinstating it would reintroduce the retired flow the assignment forbids |
| **X2** | `VerifiedCallerIdentity`, `CallerIdConsent`, and the seven CLI enums | `models.py:26-232` | Same reason. The tables are **retained** (chunk 04 dropped nothing) but must not be wired into the new route. `caller_id_consents` is consent evidence and stays for its retention period |
| **X3** | `_handle_initiated` + `_log_pstn_rejection` | `service.py:111,169` | The WebRTC→PSTN bridge built on the **client-dials** model, gated on a verified caller identity. Both premises are gone. This is the code the new topology deliberately inverts |
| **X4** | `_handle_app_to_app_hangup` | `service.py:275` | App-to-app calling between DamDam users. Not in the approved scope, which is outbound to ordinary phone numbers |
| **X5** | `callKit.ts`, `voiceGateway.ts` | deleted in `390f792` | CallKit/PushKit **incoming**-call handling. Incoming ringing is deferred; outbound-only calling needs neither. Restoring them would reinstate the `voip` background mode 04D removed |
| **X6** | `cliClient.ts`, `voiceClient.ts` | deleted in `390f792` | Clients for retired endpoints |
| **X7** | `IDTExpressVoiceProvider` | `providers.py:154` | Its own docstring says it "is never constructed in production; it exists only to give" a second provider shape. A second carrier is not approved |

## Assumptions in the retained code that must be re-examined

These are not components but embedded premises, and each one is a trap:

1. **Minutes-bundle accounting.** `pstn_minutes_total/remaining` on `Package`
   assumes prepaid minutes attached to an eSIM package. Internet calling
   **must not require an eSIM** — so a voice grant cannot hang off `Package`.
   Chunk 05's `entitlements` table is the right home; the plan calls a voice-only
   grant "a distinct capability, not a fake installed line."
2. **NGN-only money.** Retained billing assumes NGN. Telnyx bills in **USD**.
   Chunk 05 made money currency-explicit — use it, and keep FX a separate,
   versioned input.
3. **One billable leg.** Every retained billing path charges once. The evidenced
   reality is **two CDRs per call**. This is the highest-value correction in this
   inventory: carrying the single-leg assumption forward would misprice by
   roughly the WebRTC leg on every call.
4. **Caller ID from a verified third-party number.** Now an owned Telnyx number.
5. **`gencred…` SIP usernames.** The provider's own docs use that prefix for
   telephony credentials, so the retained naming is real, not invented — but
   see F2 on what such a credential must not be allowed to do.

## Traceability

Every path above is either present in the working tree at `d95db83` or
recoverable with:

```
git show 390f792 -- apps/api/app/voice/caller_identity_service.py
git show 390f792 -- apps/mobile/src/services/callKit.ts
git log --diff-filter=D --name-only 390f792
```
