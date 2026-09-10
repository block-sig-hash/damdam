# Approved calling expansion — 9 September 2026

The founder approved proceeding with the recommendation to offer outbound
internet calling in the mobile app and website, alongside carrier eSIM calling.
This records that product decision; it does not certify supplier access, shipped
features, a commercial rate, a legal seller or a release.

This amendment and PRD §11 supersede conflicting calling scope in the 8 September
plan, future chunk boilerplate and earlier retirement specifications. Preserve
chunks 01–05 and their accepted history. Do not revert chunk 04D or resurrect
family contacts, SOS, welfare dispatch, verified-CLI enrollment or incoming-call
push bridges. Selective legacy reuse requires a fresh review against this scope.

## Product and rollout

| Mode | Customer experience | Required service | Initial delivery |
|---|---|---|---|
| Mobile internet | Dial an ordinary phone number from DamDam over Wi-Fi or mobile data | Internet-calling entitlement, supported origin/destination, authorized outbound identity | Outbound first |
| Browser internet | Sign in to the customer website and dial an ordinary phone number with a microphone | Same account, entitlement and calling backend as mobile; no eSIM required | Outbound first |
| Carrier | Install a voice-enabled eSIM; use the phone's normal dialer and data | Proven carrier profile, handset, visited network and number capabilities | Enable only for verified offers |

Internet calling is sellable independently of eSIM ownership. The receiving
party needs a reachable phone number, not a DamDam app. The app must distinguish
“Call over internet” from “Call using DamDam eSIM”; a native dialer launch does
not prove the selected SIM or that a call connected. Guide line selection and
obtain carrier usage from the provider. Do not promise automatic in-call handover,
automatic cheapest routing, or native voice on a data-only profile.

Use provider-authorized assigned outbound identity. A shared DamDam number across
all three modes is a target subject to written supplier and live route evidence;
it is not a prerequisite for outbound internet calling. Show the actual identity
for each mode, and disclose callback limitations before calling. Own-number
verification, +234 retention/porting, incoming app/browser ringing and coordinated
ringing remain deferred. Native incoming calls may be sold only if independently
proven. No PBX, recording, AI, extra carrier, subscription or microservice scope
is added. Evaluate emergency-calling requirements and disclosures separately for
each mode and selling market; removal of the old SOS feature answers none of them.

## Shared backend, separate provider capabilities

Retain FastAPI/PostgreSQL/Redis workers, React Native and Next.js. Extend the
existing web application with a separate authenticated consumer calling area;
consumer access must not require organization or internal-operator privileges.
SDK media/signaling sits behind client service wrappers; server credentials,
policy, rates, authorization and charging remain on the backend. This does not
prohibit the SDK's necessary direct media connection to the provider.

The internet-calling adapter and carrier adapter expose distinct capabilities.
Record support by account/product, selling market, origin, destination, network,
device/browser, outbound identity and direction. Unknown means unavailable.
UI feature flags alone cannot enable an unsupported service.

Shared domain concepts: immutable payer/seller/currency, entitlement, versioned
rate, reservation, call attempt, provider call/leg identifiers, signed event inbox,
usage record and compensating settlement. Internet calling must not require an
eSIM installation or carrier line foreign key. Preserve chunk 05's one-recipient,
quantity-one order-item invariant; a voice-only grant is a distinct capability,
not a fake installed line. V02 owns additive schema/API proposals and migrations;
V03 owns metering/settlement additions. No schema is implemented by this plan.

At call authorization, the server binds destination, outbound identity, payer,
tenant, rate version, maximum liability and expiry to a durable attempt. A copied
SDK token must not bypass this grant, change destination or fund another call.
V01 must establish how Telnyx routing and server controls enforce this before a
live route is enabled. Never expose an unrestricted reusable SIP credential.

Reservation and settlement rules:

- Reserve atomically in PostgreSQL before permitting a billable leg. Use exact
  decimal amounts and explicit currency; concurrent browser/mobile calls compete
  for the same available funds and applicable organization budget.
- Account for connection charges, minimum/billing increments, every billable leg,
  platform fees and permitted termination delay. Estimate customer price from a
  versioned retail tariff and reconcile supplier costs separately. Do not sum leg
  durations as customer talk time or charge both a webhook and CDR for one use.
- Enforce duration/spending limits server/provider-side with a verified bound.
  Test worker failure, browser closure, lost media and delayed events. If provider
  termination cannot be bounded, a hard prepaid guarantee remains blocked.
- Unknown originate/bridge/hangup outcomes reconcile against the original attempt;
  no blind second PSTN leg, supplier failover or premature reservation release.
  Duplicate, late, reordered events and corrections converge through audited
  settlement; disable new calls while still processing existing liabilities.
- Carrier spend has its own reservation/control mechanism while the app is closed.
  A unified displayed balance is insufficient: allocate bounded carrier exposure
  separately before native use, or prove equivalent atomic provider enforcement.
  Without that, do not offer an unrestricted common spend pool or hard cap.
- Rate-limit calling and credential issuance; deny unsupported/premium destinations
  by server policy. Revoked membership blocks new work calls and triggers the
  defined active-call termination policy without affecting personal service.
  Log masked metadata, not credentials, activation secrets or recordings.

## Additional review units — stable existing numbers

All new units start NOT_STARTED. Each gets a separate implementation handoff,
Codex review and PR. Merge accepted units individually once applicable checks
pass; do not wait for groups 01–05 or V01–V05. A preparatory acceptance never
closes an external production gate. The founder's existing Claude/Codex split
and authorization boundaries still apply.

| Chunk | Story | Deliverable | Accepted prerequisites |
|---|---|---|---|
| V01 | US-44 | Internet-voice evidence, route/control contract and legacy reuse inventory | 03 documented scope, 04, 05; this approved amendment |
| V02 | US-45 | Outbound authorization, provider boundary and durable call lifecycle | V01 documented contract, 06, 07, 09, 10, 11 |
| V03 | US-46 | Metering, financial reconciliation and enforced call limits | V02, 10, 14 |
| V04 | US-47 | Mobile outbound internet calling | V03, 08, 18 |
| V05 | US-48 | Consumer browser outbound calling | V03, 08; web auth contract from 06/07 |

V01 can proceed alongside chunk 06 or independent staging work in isolated
worktrees: it changes research/contracts only. V04 and V05 may run concurrently
only after V03 acceptance, with separate worktrees and coordinated ownership of
shared API schemas and docs; neither implements missing backend dependencies.
One active implementation chunk remains the default elsewhere.

## Changes to numbered chunks

These are additions to their existing acceptance criteria, not extra features
implicitly assigned to a nearby chunk. Read this table with each assignment.

| Chunks | Required change |
|---|---|
| 06–07 | Identity/recovery and scoped personal/work sessions must work for internet-only users. Browser calling cannot require organization membership. Revoke call grants/credentials appropriately; V02 implements calling-specific controls. |
| 08 | Define Calls navigation, mode/identity/payer labels, permission/error/low-credit states, English/French and accessible mobile/web controls. Browser consumer area is distinct from enterprise admin. |
| 09–11 | Read V01's documented contract before finalizing voice-specific catalog/quote/ledger/order behavior. Model mode-specific eligibility and rates, internet-only entitlements and extensible reservation purposes; do not implement the V02/V03 call engine here. Generic work may progress before V01. |
| 12–14 | Confirm seller/processor approval and store-policy treatment for the actual internet-voice offering separately from eSIM plans; retain D3–D5 gates. Refunds and settlement preserve original payer, seller, currency and call liabilities. No processor auto-selection. |
| 15–17 | Keep carrier lifecycle/usage/control ownership; share ledger interfaces with V02/V03. Evidence for WebRTC never closes carrier gates. Number reuse and simultaneous carrier/internet exposure need proof. |
| 18–19 | Support signup and internet-only purchase/recovery with no forced eSIM/device eligibility or installation. Connect Calls only when V04 is accepted and enabled. |
| 20–21 | Keep native line guidance; add clear entry to internet Calls when available. Account, receipts/support/deletion must serve internet-only users without an installed line. Chunk 21 may split shared account/support scope from its carrier-specific dependency on 20. |
| 22–24 | Enterprise policy permits/denies calling modes and destinations per member, with shared budgets and explicit active-call offboarding behavior. Consumer browser calling is V05, not an enterprise privilege. |
| 25–26 | Separate calling exceptions and internet/carrier telemetry; reconcile orphaned billable legs and credentials. Configure webhook verification, secret rotation and supported browser-origin policy. Media transport needs are verified in V01; do not expose staging ports speculatively. |
| 27 | Include V04/V05 acceptance for released internet channels. Add outbound native SDK/microphone/store disclosures and mobile/browser signoff scenarios. Do not restore incoming PushKit/FCM/CallKit gates merely to add outbound calls. Active-call native integration is allowed where the supported SDK/OS requires it, with explicit evidence. |
| 28 | Add V02–V05 scenarios: concurrent app/browser debit, copied credential bypass, lost originate response, tab crash, worker loss, replay/late CDR, bounded termination, logout/account switch, tenant offboarding, and carrier plus internet budget contention if both are enabled. |
| 29 | Prove live outbound mobile and browser calls to Nigeria mobile/landline where sold, DTMF/audio/identity and actual costs; test other advertised routes. Test native calls separately on physical iOS/Android with DamDam closed. Record failures and unavailable evidence honestly. |
| 30 | Release only the independently proven capabilities and markets in the release manifest. Unbuilt channels remain unavailable; no generic global-voice claim. |

### Release dependency rule

The original dependency table remains the default for the combined product.
For an outbound internet release before carrier readiness, 27–30 may consume
accepted shared portions of 21/24/25 and V01–V05, with carrier-only portions of
15–17/20/23 explicitly excluded in a reviewed release manifest. Document exact
accepted prerequisite SHAs, capability flags, routes, negative eligibility tests
and remaining scope. This is a capability-specific release, never acceptance of
unfinished carrier chunks. Required auth, ledger, merchant, privacy, tenant,
support, backup, signed-device and operational evidence still applies.

D1's carrier gate stays open until proven; it need not block independently
verified internet calling. D1 gains an internet-voice evidence track under V01;
D2–D6 must be assessed for every offered mode. No new release approval or external
vendor message is implied by this planning change.

## Evidence and next action

Public sources checked 9 September 2026:

- [Telnyx WebRTC fundamentals](https://developers.telnyx.com/docs/voice/webrtc/fundamentals)
  describes client SDK calling. It supports investigating app/browser integration,
  not assuming any particular account's routes or authorization model.
- [Telnyx Mobile Voice](https://telnyx.com/products/mobile-voice) describes eSIM
  voice and number assignment. It does not establish DamDam's market/device
  coverage, commercial access or cross-product number reuse.
- [Telnyx Voice API pricing](https://telnyx.com/pricing/voice-api) is input to
  V01's all-leg cost analysis, not an accepted Nigeria retail tariff.

The earlier Yadaphone comparison supplies a browser UX reference only; no upstream
supplier attribution is treated as verified. The next assignment is
[V01](chunks/V01-internet-voice-feasibility.md), with a copyable
[start prompt](handoffs/V01-start.md). No new calling code ships in this amendment.
