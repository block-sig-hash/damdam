# DamDam implementation plan

Consolidated 8 September 2026 from the 7–8 September conversation.

Status: planning baseline for the new product direction. No application changes,
company formation, supplier purchase, payment activation, deployment, or external
enquiry is performed by this document. Earlier options are not automatically
accepted decisions. This plan supersedes conflicting recommendations in the
[earlier product discussion](damdam-product-shape.md).

Repository examined: `block-sig-hash/damdam`, local `develop` snapshot
`6790c74707a0f3e52cfedb36bc173ec83ca26663` at `/tmp/damdam-review`.
This is a planning inspection, not a fresh production-readiness certification.
Refresh the remote branch and CI/deployment evidence before implementation.

## 1. Product and decision record

Build a global eSIM and carrier-voice platform for individuals, enterprises and
government agencies, inspired by Popcorn's connectivity experience. Customers
buy and manage connectivity in DamDam, install an eSIM, and use their phone's
normal dialer and mobile data. Global is the expansion objective; each released
market, device, number type and roaming capability must be explicitly supported.

| Topic | Status | Implementation consequence |
|---|---|---|
| General consumer connectivity instead of Hajj-specific product | User decision | Remove mandatory pilgrimage, departure and Saudi-destination assumptions. |
| Family contacts and offline SOS | User decision: remove | Retire collection, UI, APIs, jobs, permissions and related alerts. |
| Remaining check-in/duty-of-care features | Recommended scope interpretation | Remove the associated welfare workflow from this generic product; do not quietly retain tracking in the enterprise dashboard. |
| Enterprise/government dashboard | User decision: included at launch | Replace tour-operator dashboard with provisioning, activation requests, employee allocations and billing. |
| Carrier SIM/eSIM voice | User decision | Same carrier-enabled eSIM provides data and native-dialer calls. App WebRTC is not the launch implementation. |
| Telnyx | User-selected launch supplier | Validate and integrate the relevant Mobile Voice/eSIM offering, subject to commercial and device gates. |
| 1GLOBAL and Lebara | User decision: evaluate later | Preserve extension points; no parallel launch integrations. |
| Bondio, other eSIM aggregators, IDT, Twilio/Vonage alternatives | Explored, not selected | Keep research and useful existing code in history; do not automatically enable fallback purchasing. |
| Verified existing caller ID | Deferred for launch | Remove the verification requirement and launch UI. Normal outbound identity is the carrier-assigned number. |
| Existing-number retention/porting | Unresolved | Proposed launch default: a new assigned number, with no promise of +234 retention. Confirm before publishing plans. |
| Modular components | User decision | Bounded backend modules, provider adapters and capability-based UI; no microservice rewrite or runtime plugin marketplace. |
| Paystack local routing | User-requested option; recommended conditionally | Preserve it for approved eligible NGN local payments through a matching merchant entity. |
| Global processor | Open; Stripe is a current candidate | Build a generic payment boundary, then activate the approved provider. |
| Apple/Google payments | Research supports wallet checkout | Offer Apple Pay/Google Pay through the processor where supported; do not design carrier-plan purchases around store billing. |
| Incorporation | Open | Isle of Man was the original preference; UK operating company and US LLC via Atlas were evaluated, not selected. |
| Launch charging model | Recommended default | Prepaid plans/top-ups and organization service balances; recurring billing is separately gated. |
| Login | Recommended default | Email-based account/recovery independent of mobile SMS, with phone details only where required. Finalize authentication methods in the product specification. |

Do not interpret removal of DamDam SOS as removal of any applicable carrier
emergency-calling obligations. Carrier support and customer disclosures are a
separate supplier/legal question.

## 2. Scope of the first production release

### Consumer mobile app

- Home: active services, remaining allowances, usage freshness, low-balance and expiry notices.
- Plans: destination/region coverage, device eligibility, full price, data and voice terms, top-ups.
- My Line: eSIM installation, assigned number, voice/data status, line settings guidance, supplier-derived usage and call charges.
- Account: identity/recovery, payment methods, receipts, support and deletion; renewal management only if subscriptions ship.
- Journey: browse → check eligibility → sign up → quote → pay → provision → install → select native voice/data line → use → top up.
- Keep secure installation guidance and timestamped last-known usage accessible offline. Do not require background location, family contacts or microphone access for ordinary carrier calls.
- Preserve the existing English/French localization foundation; revise copy and assets. Additional languages are future work.

### Enterprise and government dashboard

- Separate individual logins with organization memberships; owner, administrator, billing and member roles; administrator MFA.
- People, invitations, teams/departments and cost centers; CSV imports with row-level validation.
- Bulk quotes and orders; provision, assign and request activation with per-line progress and partial-failure recovery.
- Prepaid funding, approved line budgets, top-ups, invoices, receipts and departmental spend exports.
- Supplier-supported suspension and spending controls; clearly distinguish a requested restriction from a confirmed carrier restriction.
- Offboarding revokes work access and future spending while respecting personal services and carrier ownership/reassignment rules.
- Government is an organization category, with additional procurement/security requirements evaluated per contract. Launch does not claim universal government certification or data-residency compliance.

Dashboard provisioning does not install an eSIM silently on an unmanaged phone.
The employee installs/consents unless a separately supported managed-device
workflow exists. Organization credit is not automatically a shared carrier data
pool. A personal/work payer selection in the app cannot override the native
SIM line selected for a call.

### Internal operations

Use a distinct privileged interface for customer support, supplier exceptions,
payment reconciliation, refunds/disputes, catalog changes, line suspension,
organization approval and audited adjustments. Enterprise administrators never
inherit cross-customer internal access.

### Deferred

External verified caller ID, app/browser VoIP, +234 porting until supported,
additional carrier integrations, SSO/SCIM, MDM deployment, reseller marketplace,
PBX/SIP features, referral rewards, AI call assistance and multi-region deployment.
Recurring subscriptions may be promoted into scope after the pricing and renewal
decision; the foundational data model should support them. Family/SOS workflows
are removed, not included as an automatic future module.

## 3. What the repository already provides and what must change

| Existing area | Reuse | Required change / evidence boundary |
|---|---|---|
| React Native, FastAPI, PostgreSQL, Redis/Celery, Next.js | Retain the stack and deployment approach | A modular monolith is sufficient for the launch. |
| `apps/api/app/auth/models.py`, `auth/hto.py`, `auth/dependencies.py` | Users, organization types and authentication primitives | Enterprise/government enum values exist, but access checks enforce HTO and organization credentials. Introduce individual memberships and tenant authorization. |
| `apps/api/app/manifests/`, dashboard manifest pages | CSV parsing, order and recipient concepts | Generalize into people imports and bulk allocations; replace HTO licence and pilgrimage assumptions. |
| `apps/api/app/payments/`, `packages/models.py`, `manifests/orders.py` | Payment adapters and transaction workflow | Replace NGN-only amounts and processor-limited contracts; separate seller, payer, recipient, currency and settlement. |
| `apps/api/app/esim/providers.py` | Provider boundary and pending-order safeguards | Existing issue-only contract does not implement Telnyx native voice. Monty/1GLOBAL HTTP adapters expect normalized partner endpoints; their existence is not proof of a live integration. |
| `apps/api/app/voice/`, mobile `voiceGateway.ts` and `callKit.ts` | Relevant billing concepts and historical implementation | Existing Telnyx path is app/WebRTC calling. Add carrier line/number lifecycle and billing; remove app-call SDK/UI from the launch dependency graph where unused. |
| Mobile `AuthenticatedApp.tsx`, onboarding, Home | Components, theme, localization and session handling | Navigation currently combines SOS/check-ins/CLI/app calls and package/departure state. Replace with the new account/line/plans structure. |
| Family/profile, check-ins, SOS, arrival geofencing | Shared notification/auth utilities where still needed | Retire feature-specific collection and dispatch with a migration and old-client plan. |
| `docs/pre-pilot-checklist.md`, release signoffs and validator | Evidence-based release discipline | Existing gates target Hajj/SOS/WebRTC/verified CLI. Replace obsolete gates with carrier, payments and enterprise evidence; retain release protection. |
| CI, native projects, backups and deployment scripts | Existing automation | Re-establish current baseline. Historical notes about unsigned builds, missing secrets or staging failures must be rechecked, not repeated as current facts. |

The repository's old feature freeze and UAE-parent corporate recommendation are
superseded by the user's explicit redesign request. Record that scope change in
the first documentation PR; do not treat the redesign as an unauthorized exception.
Retain existing release tags and historical migrations.

### 3.1 Explicit disposition of the five original review findings

Added 8 September after the user supplied the original review. The first plan
covered these areas at phase level but did not explicitly carry forward the
account-switch defect or the two named CI failures. This table closes that
traceability gap; none of these defects is declared fixed by this document.

| Original finding | Work and acceptance criteria in the new scope | Delivery |
|---|---|---|
| 1. Offline safety events can sync as the wrong signed-in user | Retire the queues safely as part of safety-feature removal. Any retained transition path must store owner identity, filter reads/dispatch by owner, and invalidate in-flight work on account changes. Legacy rows without trustworthy ownership must not be assigned to the current user; quarantine them under the retirement policy. Test A queues offline → sign out → B signs in → no A event is sent as B, including restart and delayed callbacks. If the old safety product remains live during transition, ship isolation there before further release. | Phase 1 / PR-04; prioritize transition protection if any affected build is deployed |
| 2. Purchase/install screens and activation codes are disconnected | Connect signup → plan purchase OR organization invitation/code redemption → provision/install → Home/My Line. Remove family/departure steps. Wire valid activation links/codes from app entry through authentication; verify cold/warm launch, expired/already-used code, back navigation and returning-user service recovery. Bind redemption to the intended recipient. | Phase 4 / PR-11–12, with enterprise assignment in PR-14 |
| 3. Display refresh does not measure data consumption | Implement actual supplier usage polling and/or supported events, persistent cursors, retries, deduplication, stale-reading indicators and reconciliation. Test real consumption reducing the displayed allowance; handle delayed/reordered/corrected readings without double debit. An initialized database balance or screen refresh alone cannot pass. | Phase 3 / PR-10; consumer presentation in PR-12 |
| 4. Initial order timeout can trigger a second supplier purchase | Persist an operation reference and supplier attempt before dispatch. Classify accepted/pending, definitively rejected and outcome-unknown separately; a lost initial response or crash after acceptance must reconcile with the original supplier. Retry using documented supplier idempotency, or stop for manual reconciliation if lookup is inadequate. Prove the accepted-but-response-lost scenario does not purchase a second profile, including after worker restart. Applies even with only Telnyx enabled. | Phase 2–3 / PR-06 and PR-09; preserve safeguards in any retained legacy adapter |
| 5. API clock mismatch and iOS screenshot CI failures | Reproduce/fix inconsistent clocks in token creation and JWT validation with one controlled test clock; test valid and expired tokens without disabling production expiry checks. Repair iOS screenshot generation and require a complete, nonempty screenshot manifest for the revised screen/locale matrix. Re-run API/mobile/dashboard and relevant build checks; complete physical carrier/payment/installation tests. The historical 32-image count applies to the old matrix, not the redesigned app. | Phase 0 baseline repair / PR-16 early work; Phase 6 / PR-17 release proof |

Original CI observation supplied in the conversation: 335 API tests passed,
one failed, 87% coverage; iOS screenshot output was 0/32, while mobile unit and
dashboard checks passed. This describes the September 7 review, not a newly
executed test run. [Original CI evidence](https://github.com/block-sig-hash/damdam/actions/runs/34094962267).

Safe queue retirement replaces rebuilding SOS for the new product. Offline SOS
recovery and verified-CLI call tests cease to be new-product release criteria
only after their features and supported transition paths are actually retired.
Retain account isolation for all remaining cached/offline data and jobs.

## 4. Architecture and data contracts

Core modules: Identity; Organizations; Catalog/Eligibility; Orders; Payments;
Ledger; Connectivity; Notifications; Support/Audit. Keep providers behind
internal interfaces, not in route handlers or UI components.

- Identity: account identities and recovery methods are independent of assigned carrier numbers.
- Organizations: memberships, invitations, roles, recipients and cost centers. Enforce scope in APIs, background jobs, exports and storage access.
- Catalog: products, supported markets/networks/devices, supplier SKU mappings, voice origins/destinations, price/rate versions and expiry.
- Commerce: immutable quotes, order items, payer, service recipient, selling legal entity, tax treatment, payment attempts and refund references.
- Connectivity: device, eSIM profile, carrier line, number, service entitlement and activation request are separate resources. Reuse/top-up is capability-dependent.
- Ledger: immutable balanced entries, currency-specific accounts, funding, reservations, consumption, releases and compensating adjustments. No cross-currency balance addition.
- Usage: unique supplier event identifiers, occurrence and receipt times, units, rate version and reconciliation status. Distinguish provisional usage from finalized billing.
- Events: durable outbox/inbox and idempotent consumers for paid orders, provisioning, usage and notifications. Apply these to recoverable workflows rather than converting the whole system to event sourcing.

Keep payment, provisioning, installation, activation and connectivity states
separate. A paid order may be pending provisioning; installation does not prove
network attachment. Unknown supplier status triggers reconciliation with the
same operation reference, not a second purchase with another vendor.

Money uses explicit ISO currency and correctly scaled amounts; rates and metered
usage need exact decimal precision and documented rounding. Preserve historical
NGN records during migration, including receipts and refunds.

Each provider advertises capabilities such as native voice, supported numbers,
top-up, reuse, suspension, usage latency and spending enforcement. A data-only
adapter cannot satisfy a native-voice plan. Switching carriers may require a new
eSIM and customer action, not merely a configuration update.

Optional product modules own their API, permissions, jobs, UI entries and tests.
Disabling a module prevents new actions while allowing refunds/reconciliation of
existing liabilities. Native features can require app updates.

## 5. External decisions and launch dependencies

These investigations can run alongside engineering. No company formation,
supplier contract, paid test order or outgoing enquiry is implied by this plan.

| ID | Owner | Deliverable | Blocks |
|---|---|---|---|
| D1 | Founder + Telnyx commercial/technical team | Written consumer-handset/resale eligibility; VoLTE beta access/production support; SIM, mobile voice, number and device/network coverage; remote activation; permitted roaming; test account and rate deck | Live carrier implementation acceptance and saleable catalog |
| D2 | Founder/product | First selling markets, visited countries, calling destinations, supported devices and number policy; distinguish all four kinds of coverage | Public claims and launch eligibility rules |
| D3 | Founder + cross-border tax/legal advisers | Entity/ownership/management decision comparing US LLC, UK and Isle of Man, including Nigerian treatment and real annual costs | Merchant onboarding, seller identity and tax configuration |
| D4 | Founder + payment providers | Written telecom approval, merchant/settlement eligibility, fees, FX, reserves, refunds, disputes and renewal support | Live payments |
| D5 | Founder/product + finance | Prepaid versus recurring choice; SKU margins; refund policy; enterprise funding/credit policy | Final checkout and billing behavior |
| D6 | Founder + release owner | Apple/Google developer access, signing, domains, hosting, secrets, support ownership and physical test devices | Signed staging builds and production release |

Telnyx evaluation must include calls TO Nigeria: local/mobile network and
landline rates, originating home line and visited network, connection fees,
billing increments, inbound charges, roaming, minimum commitments and taxes.
Candidate test journeys discussed were Nigeria→Nigeria, Saudi Arabia→Nigeria
and UK→Nigeria; these are test candidates, not confirmed coverage.

Hard spending limits require supplier-side control that works while the app is
closed. Test exhaustion, delayed usage and concurrent calls. If this cannot meet
the offered prepaid contract, revise that contract before launch. Do not present
an app-side balance based on delayed records as a guaranteed hard cap.

If Telnyx cannot deliver the required native-voice experience in a proposed
market, exclude that market and resolve the product/supplier decision. Do not
silently substitute app VoIP or launch a data-only product as if it satisfied
the user's chosen experience.

### Telnyx product verification — 8 September 2026

Telnyx's [eSIM-as-a-Service page](https://telnyx.com/products/esim) explicitly
supports branded data eSIM resale. Its [Wireless overview](https://developers.telnyx.com/docs/iot-sim/wireless-overview)
documents data, VoLTE and messaging; [SIM resource documentation](https://developers.telnyx.com/docs/iot-sim/get-started)
places physical SIMs and eSIMs under the same SIM Card resource with optional
voice. This supports evaluating Telnyx as the launch supplier for both data and
native voice, replacing the separate data-aggregator/app-voice arrangement.

The [VoLTE overview](https://developers.telnyx.com/docs/iot-sim/voice-enabled-iot)
currently labels the product **beta**. Confirm access, supported production use,
API stability, support commitments and service-specific coverage before release.
The marketing page alone does not resolve these commercial readiness questions.

Telnyx documents multiple IMSIs and automatic selection in its
[IMSI guide](https://developers.telnyx.com/docs/iot-sim/imsi-selection).
The 650+ networks / 180+ countries eSIM claim is not proof that voice, inbound
calls, SMS/MMS/RCS, local numbers or permanent roaming work in every such market.
Ask for a matrix by profile/IMSI, visited network, device and service. Do not
promise uninterrupted calls across IMSI switching without device/network evidence.

The [Mobile Phone Numbers guide](https://developers.telnyx.com/docs/iot-sim/mobile-phone-numbers)
documents enabling voice on a SIM, assigning a mobile number, native incoming
ringing and the assigned number as outbound caller ID. It does not establish
arbitrary third-party verified +234 caller-ID presentation on that cellular line.
External CLI preservation is already deferred by the user and is **not a launch
disqualifier**. Retain it as a future commercial question, separate from porting.

D1 questions to resolve: can the same resold eSIM support simultaneous data and
native incoming/outgoing voice in each chosen market; which assigned number
countries are available; what is required for first activation and voice roaming;
what are the all-in Nigeria calling rates; how are caps/usage/corrections exposed;
and what production terms apply while VoLTE is in beta? Confirm messaging options
separately rather than adding SMS/MMS/RCS to the initial committed scope.

## 6. Payments, entity and tax planning record

### Payment design

Preferred architecture: approved local NGN payments → Paystack; international
payments → approved global processor; enterprise contracts → invoice/bank
transfer or supported cards. Route according to merchant eligibility, seller,
currency and payment method, not nationality or IP alone. Do not switch the
legal seller invisibly after an order has been accepted.

Apple Pay and Google Pay are checkout methods through a processor. Store billing
is not the proposed carrier-plan collection mechanism. Review any future paid
in-app software feature separately. Airalo documents Stripe; Airalo, Nomad,
Holafly and Ubigi document card/wallet checkout; Popcorn documents its own stored
card and subscription management. Public docs are precedents, not guaranteed
approval for DamDam or a complete audit of every regional payment flow.

Paystack's international restrictions include data resellers/instant-value
businesses. Local approval remains a separate question. A Nigerian collection
entity/agent arrangement needs matching contracts, settlement and processor
approval; do not use an unrelated merchant account. Any service balance is
closed to DamDam connectivity, without peer-to-peer transfers or general cash-out.

Refunds retain the original seller and processor reference. Validate signed
webhooks, account, amount, currency and final payment status before fulfillment.
Duplicate, late or reordered events cannot produce duplicate money or service.
Reconcile uncertain charges before asking the customer to retry elsewhere.

### Entity alternatives discussed, still undecided

| Option | Decision input to obtain |
|---|---|
| Isle of Man | Direct processor eligibility and banking; Stripe does not treat it as supported UK incorporation. Adyen/Checkout.com were enquiry candidates, not approved providers. |
| UK company | Worldwide-profit Corporation Tax for a UK-tax-resident company; associated-company thresholds; VAT/telecom rules; personal withdrawals; management from Nigeria and any parent relationship. |
| US LLC through Stripe Atlas | Sole/multiple ownership, US tax status, default/elected classification, US business activity and communications-income sourcing; Nigerian classification/residence; state/telecom taxes; 5472/pro forma 1120 and annual Delaware obligations. |

Do not turn the earlier illustrative tax rates into automatic checkout rules or
assume foreign ownership means no tax. Atlas formation does not guarantee Stripe
Payments approval. US corporate taxation and dividend withholding differ from
default disregarded-LLC treatment. A foreign tax classification may not be
recognized the same way in Nigeria. Keep a tax calendar and adviser-confirmed
allocation and records policy before taking live payments.

Model price economics per SKU: customer price excluding collected tax less
carrier/eSIM/number/voice cost, processor fees, FX, expected refunds/disputes,
support and recurring overhead. Do not infer a retail margin from a SIP rate
alone. Obtain actual quotes rather than committing to yesterday's public rates.

## 7. Implementation phases and completion criteria

### Phase 0 — Rebaseline the product and prove feasibility

Deliver: refreshed branch/CI inventory; revised PRD and acceptance criteria;
amended API/data/mobile/dashboard/security/corporate/release docs; updated design
system for the generic product; D1–D6 decision register with owners and evidence.
Run a small physical-device carrier proof as soon as supplier access exists.

Exit: scope conflicts are resolved in repository docs; story IDs and tests are
mapped; no claim that the old WebRTC RC proves Mobile Voice. Engineering can
continue on stable contracts while company and supplier answers remain pending.

### Phase 1 — Core model, identities and safe feature retirement

Deliver: additive model migrations, individual organization memberships and
roles, global identity/recovery, seller/payer/recipient separation; remove family,
welfare and launch CLI/app-call dependencies across API/mobile/dashboard.

Migration sequence: inventory actual deployments and stored data → disable new
feature enrollment/dispatch → handle queued work and legacy clients explicitly →
backfill required new fields → verify migration and rollback → delete sensitive
legacy records according to the approved retention policy → remove obsolete schema
only after compatibility requirements end. Do not erase order/audit history or
drop production tables merely because a screen was removed.

Exit: accounts can recover without the removed flows; unauthorized cross-tenant
access fails; old clients/jobs cannot revive removed notifications; no unused
contacts, background location or app-call permissions in release builds.

### Phase 2 — Catalog, orders, ledger and payments

Deliver: supported-market catalog, immutable quotes, multi-currency money, order
state machine, ledger, Paystack adapter retained conditionally, approved global
adapter, hosted/tokenized checkout, receipts, refunds, disputes and bank funding.
Avoid collecting raw card details in DamDam's backend.

Exit: concurrent requests and repeated/reordered webhooks cannot double-charge,
double-credit or double-provision; unknown outcomes are recoverable; tax/FX/fees
reconcile; currency mismatches fail; a refund maps to the correct original charge.
Test mode can close software work; live merchant approval remains a launch gate.

### Phase 3 — Telnyx carrier eSIM and voice

Deliver: real supplier adapter, product mappings, idempotent provisioning and
lookup, line/number lifecycle, activation, supported top-ups/reuse, suspension,
usage ingestion/reconciliation, tariff versions and supplier spending controls.

Exit: on approved physical iOS and Android devices, install the supported eSIM,
use data and place a native-dialer call to Nigeria with DamDam closed. Prove
inbound calls if sold, correct assigned caller ID, billed cost, top-up and limit
behavior. Capture visited network, device/OS, supplier references and rate version.
No simulator-only or WebRTC evidence closes this gate.

### Phase 4 — Consumer experience

Deliver: complete Home/Plans/My Line/Account navigation; onboarding and recovery;
eligibility; payment/pending/failure states; installation guides and QR fallback;
line selection guidance; usage freshness; receipts, support and deletion.
Replace placeholder device guides for the supported launch matrix. Update both
languages and accessibility/screenshot coverage against the revised design system.

Exit: a new user completes purchase through use and top-up without developer
intervention. An unsupported or locked device receives useful guidance before
payment; installation failure and account recovery have tested routes.

### Phase 5 — Enterprise/government and operations

Deliver: People/Teams, bulk provisioning, assignment/invitations, activation
requests, prepaid funding and limits, reports and offboarding; distinct internal
support with exception queues and audited adjustments.

Exit: a representative organization imports 50 recipients, reviews a quote,
funds an order, handles partial failures and assigns service without duplicate
charges. Restricted administrators cannot cross role/tenant boundaries. Employees
install services, the organization sees reconciled spend, and offboarding works.
Observe a real pilot administrator using the flow and fix material issues.

### Phase 6 — Production operations and controlled release

Deliver: isolated staging/production, secrets and least-privilege credentials,
verified webhooks, migrations, backups and restoration, monitoring and alerting,
signed iOS/Android builds, store privacy/payment disclosures, support/refund
runbooks and a tested release/rollback procedure.

Exit: all launch criteria in section 10 have evidence against the release
commit. Launch a limited approved market/customer cohort, including an enterprise
pilot, then expand based on supplier capacity, call quality, support load and
payment/provisioning reliability. Cut a new release candidate; keep old tags intact.

## 8. Suggested PR-sized backlog

Execution update: use the [Claude build and Codex review pack](README.md)
for the detailed 30-chunk sequence, dependencies, handoff and review criteria.
It splits the broader PRs below into smaller assignments and brings CI repair
and carrier feasibility forward. These PR/story IDs remain traceability references.

The IDs below are proposed new stories to add to the PRD in PR-01. Retain old
US-01…US-26 IDs as historical references and map each to retained/replaced/retired
criteria; do not reuse an old ID for an unrelated requirement. Each PR references
its registered story and relevant acceptance tests.

| PR | Story | Deliverable | Depends on |
|---|---|---|---|
| 01 | US-27 | Product reset, old-story disposition, architecture decisions, design/release gate amendments | None |
| 02 | US-28 | Core schema/contracts, migration/backfill design, market and seller definitions | 01 |
| 03 | US-29 | Individual accounts, recovery, organization membership/RBAC/MFA | 02 |
| 04 | US-30 | Safe family/check-in/SOS retirement and removal of launch CLI/app-call dependencies | 01–03 |
| 05 | US-31 | Catalog, coverage eligibility, tariff versions and immutable quotes | 02; D1/D2 for live catalog |
| 06 | US-32 | Multi-currency ledger, orders, reservations and durable recovery | 02, 03, 05 |
| 07 | US-33 | Payment routing, Paystack modernization and approved global adapter | 06; D3/D4 for live mode |
| 08 | US-34 | Refunds, disputes, payout/bank reconciliation and receipts | 07 |
| 09 | US-35 | Telnyx carrier profile/line/number lifecycle and provisioning recovery | 02, 05, 06; D1 |
| 10 | US-36 | Carrier usage, charging, caps, top-ups and suspension | 09; tariff/control evidence |
| 11 | US-37 | Consumer onboarding, navigation and plan checkout | 03–07; revised design system |
| 12 | US-38 | My Line, installation, usage, support and recovery completion | 08–11 |
| 13 | US-39 | Enterprise people/imports, memberships and assignment UI | 03, 05, 06 |
| 14 | US-40 | Enterprise bulk orders, activation, spend and offboarding | 08–10, 13 |
| 15 | US-41 | Internal operations, exception queues and audit/report exports | 08–10, 14 |
| 16 | US-42 | Environment/signing/release automation and operational evidence | 01; develop alongside other PRs |
| 17 | US-43 | Physical-device/customer pilot fixes and release signoff | 12, 14–16; D1–D6 resolved |

PRs are delivery boundaries, not a promise that each fits in one day. Split
schema, auth and financial changes further when needed for review. The small
carrier feasibility exercise in Phase 0 precedes substantial supplier-dependent
UI investment. Infrastructure and enterprise foundations can progress alongside
the consumer work once their shared contracts exist.

Critical path: confirmed supplier capabilities + seller/merchant eligibility →
paid order → carrier provisioning → real data/native voice → reconciled usage
and enterprise controls → signed release with operational proof.
Set calendar dates after access, team capacity and the carrier proof are known.

## 9. Test and migration discipline

- Follow repository strict TDD for authentication, payments and idempotency;
  extend the acceptance matrix for new ledger and tenant-boundary risks.
- During removal of safety code, run applicable existing queue/dispatch tests
  and new retirement tests. Remove obsolete ongoing SOS gates through explicit
  spec/template/validator changes; do not bypass the entire release gate.
- Run API tests with PostgreSQL, Ruff, mypy and OpenAPI drift checks; mobile
  Jest/lint/type checks; dashboard Vitest/lint/type checks and production build.
- Test fresh database installation and upgrade from the existing schema with
  representative accounts, organizations, paid orders and pending jobs. Verify
  historical receipts, balances and identifiers after backfill.
- Exercise simultaneous purchases, double webhooks, delayed settlement, supplier
  timeouts, partial bulk orders, stale usage and reconciliation replay.
- Scope device tests by exact hardware/OS/carrier support, including negative
  cases. Do not claim every Tecno/Infinix/itel/Samsung model supports eSIM.
- Validate native voice separately from app permissions/CallKit; test closed-app
  calling, inbound where sold, audio quality, DTMF, dual-SIM selection and charges.
- Adapt existing release-signoff validator and screenshot harness to the new
  scenario matrix. Staging/production execution evidence is separate from CI.

## 10. Production launch checklist

- [ ] Chosen entity, owner/management facts and tax/telecom responsibilities documented.
- [ ] Approved merchant account(s), bank settlement and truthful seller disclosures.
- [ ] Telnyx resale/native-voice agreement, rate deck and supported-market matrix recorded.
- [ ] One real supported consumer purchase → eSIM install → data → native call to Nigeria → usage → top-up succeeds on both platforms.
- [ ] Unsupported-device, declined payment, paid-but-pending, failed installation and refund journeys work.
- [ ] Every financial transaction is idempotent and reconcilable; no unexplained ledger discrepancies in pilot evidence.
- [ ] Voice spending enforcement matches the promised prepaid/budget behavior while the app is closed.
- [ ] Enterprise bulk allocation, partial failure, role restrictions, cross-tenant denial and offboarding verified.
- [ ] New account recovery, personal/work separation and data deletion work without family/CLI/SOS dependencies.
- [ ] Release contains no mock supplier mode, guide placeholders or accidental old-feature collection/notifications.
- [ ] Privacy, retention, app-store disclosures, terms, refunds and support reflect the actual product and launch jurisdictions.
- [ ] Production signing, monitored staging deployment, backup restore and rollback tested; secrets remain outside source control.
- [ ] English/French content, accessibility and actual device guides reviewed for supported markets.
- [ ] Measurable pilot limits and release thresholds agreed for provisioning success/latency, call setup/drops, reconciliation delay, payment failure and support response.
- [ ] New release signoff identifies the tested commit, supplier configuration, devices/networks, results, incident owner and rollback decision.

Do not mark the app production-ready merely because the implementation PRs or
automated tests pass. The carrier, merchant, physical-device and operational
evidence are part of the release deliverable.

## 11. Research retained from the conversation

Evidence below was discussed/reviewed on 7–8 September 2026; verify current
commercial terms before contracting. This is not a fresh legal/tax opinion.

- [Telnyx mobile-number/voice documentation](https://developers.telnyx.com/docs/iot-sim/mobile-phone-numbers) and [Mobile Voice pricing](https://telnyx.com/pricing/mobile-voice): distinguish carrier service from existing app WebRTC.
- [1GLOBAL](https://www.1global.com/telco-as-a-service), [Lebara Nigeria](https://lebara.ng/) and [Bondio](https://bondio.co/): previously evaluated; capabilities, wholesale partnership and Nigerian numbering are not assumed.
- [Yadaphone](https://www.yadaphone.com/en-US/call-from-laptop), [its Nigeria calling page](https://www.yadaphone.com/en-US/call/nigeria/from/united-states), and [Twilio Nigeria rates](https://www.twilio.com/en-us/voice/pricing/ng): browser/PSTN pricing context, not comparable carrier-eSIM quotes. Reported provider use does not establish a quality winner or actual routing shares.
- [Paystack international eligibility](https://support.paystack.com/en/articles/2127682), [merchant requirements](https://support.paystack.com/en/articles/2128898), [pricing](https://paystack.com/pricing): local and international processing require separate treatment.
- [Stripe territory eligibility](https://support.stripe.com/questions/stripe-availability-for-outlying-territories-of-supported-countries?locale=en-GB), [Atlas](https://stripe.com/atlas), [Atlas approval limitations](https://docs.stripe.com/atlas/signup?locale=en-GB): incorporation/payment eligibility are separate decisions.
- [Apple payment rules](https://developer.apple.com/app-store/review/guidelines/#other-purchase-methods), [Google payments policy](https://support.google.com/googleplay/android-developer/answer/9858738?hl=en), [Google policy explanation](https://support.google.com/googleplay/android-developer/answer/10281818?hl=en): assess carrier plans separately from paid software features.
- [Airalo Stripe disclosure](https://www.airalo.com/blog/whats-airmoney-how-does-it-work), [Nomad methods](https://www.nomadesim.com/help-center/en/articles/9886349-what-payment-methods-can-i-use), [Holafly app checkout](https://esim.holafly.com/news/holafly-esim-app/), [Ubigi top-ups](https://cellulardata.ubigi.com/top-up/?wmc-currency=USD), [Popcorn card management](https://help.popcorn.space/en/articles/14600141-how-do-i-update-my-card-on-record): industry checkout precedents.
- [UK Corporation Tax](https://www.gov.uk/corporation-tax), [rates](https://www.gov.uk/corporation-tax-rates), [telecom VAT guidance](https://www.gov.uk/guidance/the-vat-rules-if-you-supply-digital-services-to-private-consumers): inputs to entity/pricing advice, not an accepted UK structure.
- [IRS LLC classification](https://www.irs.gov/businesses/small-businesses-self-employed/single-member-limited-liability-companies), [ECI](https://www.irs.gov/individuals/international-taxpayers/effectively-connected-income-eci), [communications sourcing](https://www.law.cornell.edu/cfr/text/26/1.863-9), [5472 instructions](https://www.irs.gov/instructions/i5472), [Delaware annual requirements](https://corp.delaware.gov/faqs/): required US LLC assessment.
- [Nigeria Tax Act 2025](https://www.nipc.gov.ng/wp-content/uploads/2025/07/Nigeria-Tax-Act-2025.pdf), [US treaty list](https://www.irs.gov/businesses/international-businesses/united-states-income-tax-treaties-a-to-z): residence/classification and double-tax relief must be evaluated across jurisdictions.

The [earlier payment-provider enquiry](damdam-payment-provider-enquiry.md) remains
an unsent draft. Revise it for the chosen candidate entity and add a Paystack
domestic-eligibility enquiry before any authorized outreach.

## 12. Immediate next work

Start PR-01: amend the repository specifications for this product, map retired
stories, define the new acceptance criteria and replace obsolete release gates.
Then establish the core contracts and migration plan in PR-02. In parallel,
prepare the Telnyx capability/rate checklist and entity/merchant decision brief
for the founder. Do not make foundational refactoring depend on a final processor
choice, and do not build live supplier assumptions into the catalog before D1.
