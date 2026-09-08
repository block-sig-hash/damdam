# DamDam — proposed product shape

Working discussion draft, 7 September 2026. This records a proposed direction;
it does not change the repository's implementation or declare a release ready.

Update, 8 September 2026: the [consolidated implementation plan](IMPLEMENTATION-PLAN.md)
now records the full conversation, including local Paystack routing, store versus
wallet checkout, industry precedents and the US LLC/Stripe Atlas option. Use that
plan for sequencing and decision status; this file preserves the earlier discussion.
The final entity and global payment processor remain undecided.

## Direction

DamDam becomes a connectivity platform for individuals, enterprises, and
government agencies: buy and manage eSIM data, make calls, and manage personal
or organization-funded service. Availability is explicit by customer market,
destination, device, and supplier capability.

The user has requested removal of family contacts and offline SOS. The
recommendation is to remove the entire check-in/SOS welfare workflow from the
consumer core. The user has requested replacing the tour-operator dashboard
with an enterprise dashboard, including government agency accounts, in the
initial product. A separate internal support and operations interface remains
essential. The user now explicitly prefers carrier SIM/eSIM voice: activate
one eSIM, use mobile data, and make calls through the phone's native mobile
line. This replaces the earlier proposed app-VoIP launch. The user's wish to
keep their regular number remains relevant, but external caller-ID verification
does not automatically assign that number to a carrier eSIM.

The user has selected Telnyx for launch. Use Telnyx Mobile Voice for the
required carrier calling experience, subject to completing its coverage,
commercial, and physical-device validation. 1GLOBAL and Lebara are deferred
for later evaluation when needed; they are not parallel launch integrations.
The preferred corporate jurisdiction is the Isle of Man, with incorporation
status and flexibility still to be clarified. Payment processor selection is
open and must account for the entity and telecom service being sold.

## Decisions still open

1. Numbering at launch: whether a new carrier-assigned number is acceptable,
   or the service must retain the customer's existing Nigerian number. The
   latter needs supported porting or a specifically agreed carrier identity
   arrangement. A +234 number cannot simply be ported to any foreign carrier.
2. Customer eligibility at launch: international customers in supported markets,
   or Nigerian customers initially with international destination coverage.
3. Charging: recommend prepaid data bundles and calling credit initially, with
   a data model that supports recurring plans. A monthly plan can be an initial
   product if supplier economics and payment renewal support are established.

## Customer experience

Suggested navigation for the carrier product:

- Home: current service status, remaining data/calling balance, next useful
  action, low-balance/expiry notices, and support.
- Plans: eligible voice-and-data plans, country/regional/global coverage,
  roaming and calls-to-Nigeria pricing, top-ups, and renewals.
- My Line: assigned number, eSIM installation, voice/data status, allowances,
  supported settings, and timestamped supplier usage/call records.
- Account: profile, security/recovery, language, payments, receipts, support,
  subscriptions where offered, and account deletion.

The main journey is browse coverage -> check compatibility -> sign up -> buy ->
install -> select the line for calls and data -> connect -> use -> top up or
renew. Calls use the phone's ordinary dialer; DamDam manages the service.
The app need not stay open for carrier calls. Departure dates, location access,
and another person's contact details are not prerequisites for buying data.

Recommend an email-based account with a recovery path independent of cellular
SMS reception. Login identity, the carrier-assigned number, and any optional
verified app-calling identity are separate resources. Final authentication
methods remain a design choice.

Keep installation instructions, eSIM details, and timestamped last-known usage
available offline. Removing offline SOS does not remove useful offline access.

## Enterprise and government experience

Use the same mobile app for organization-sponsored service, with a clear choice
of personal versus work service where both exist. On dual-SIM devices the
selected calling line determines who pays for carrier calls; the dashboard
cannot arbitrarily change that through an app-only wallet selection. The enterprise web dashboard
manages only that organization's people, purchased services, and spending.
Government is an organization category within the same product; additional
contractual requirements are assessed per customer.

Suggested dashboard navigation: Overview, People & Teams, eSIMs & Plans, Voice,
Billing, Reports, and Settings. Initial capabilities:

- Invite individual staff administrators and employees; import recipients by
  CSV with row-level validation and results.
- Group recipients by department, project, or cost center.
- Quote, buy, provision, and assign voice-and-data lines/plans in bulk, with per-recipient
  progress and safe retries when some orders fail.
- Deliver installation instructions through the app or a secure invitation.
  Request supplier-side activation when supported and show installation,
  activation, and first connectivity as separate states where observable.
- Allocate organization calling credit with per-person limits, permitted
  destinations, and organization-wide spending controls. Hard carrier-call
  limits require supplier-side prepaid charging or barring enforcement;
  delayed call records and an app-side balance cannot guarantee a hard cap.
- Display usage with its last update time; top up, restrict future spending,
  and request service suspension where the supplier supports it.
- Fund a prepaid organization balance, see invoices/receipts and transaction
  history, and export departmental usage and spend.
- Manage owner, administrator, billing, and member roles, with administrator
  MFA, tenant isolation, and an audit trail of provisioning and billing actions.

Example: an agency administrator imports 50 staff, chooses destination plans,
reviews the total quote, funds the order, and assigns data and calling budgets.
Each employee accepts the invitation and installs their eSIM. The administrator
tracks each allocation and tops up or restricts service as needed.

Dashboard provisioning does not by itself install an eSIM on an unmanaged
phone. Automatic deployment to managed devices is a later integration requiring
compatible devices, device management, and carrier support. Apple documents
the carrier and device-management coordination for this workflow:
https://support.apple.com/guide/deployment/a-device-management-service-deploy-devices-dep12504a832/1/web/1.0

An organization balance is an accounting feature; it does not imply supplier
support for a shared data pool. Employee departure revokes work access and
future organization spending while preserving personal service. Do not assume
an installed eSIM can be reassigned to another device or person.

## Voice scope and costs

Selected direction: carrier voice and data on the same eSIM, with native dialer
calling. Require a voice-enabled carrier profile and supported device/network
registration. A separate data eSIM plus a generic SIP API does not provide this
experience automatically. Normal outgoing identity is the carrier line's number.
Confirm inbound voice, SMS, Wi-Fi calling, and number retention separately.

Supplier evidence (Telnyx selected; 1GLOBAL and Lebara deferred):

- 1GLOBAL: explicitly offers white-label domestic eSIM data, calls, texts, local
  numbers, and porting in supported markets. Its page distinguishes domestic
  plans in 10 countries from data roaming in 200+ destinations. Those numbers
  do not establish voice roaming everywhere, Nigerian home service, or +234
  porting. Obtain a country/network/device voice matrix and wholesale quote.
  https://www.1global.com/telco-as-a-service
- Telnyx Mobile Voice: a different product from app WebRTC calling. Official
  docs support voice activation on individual/bulk SIMs, assigned mobile
  numbers, native incoming ringing, and outgoing line caller ID. Public pricing
  requires a custom rate and combines carrier charges with SIP termination;
  the displayed carrier table names US networks. Global data coverage alone
  does not establish global mobile voice support. Request Nigeria and roaming
  capability explicitly, including ordinary consumer handset/resale support.
  https://developers.telnyx.com/docs/iot-sim/mobile-phone-numbers
  https://telnyx.com/pricing/mobile-voice
- Lebara Nigeria: advertises eSIM, local voice/data, and enterprise services.
  Its homepage contains inconsistent porting information: setup instructions
  mention porting, but the FAQ says keeping a current number is not yet
  available. Wholesale/API access, porting, and international voice roaming
  must be confirmed directly. Treat this as a potential Nigerian carrier
  partner, not a confirmed global supplier.
  https://lebara.ng/
- Bondio: keep under evaluation, but the public eSIM/data site does not prove
  the native-dialer voice, numbering, and roaming capabilities needed here.
  https://bondio.co/

Request the Telnyx quote for Nigeria-to-Nigeria, Saudi Arabia-to-Nigeria, UK-to-Nigeria,
and other launch travel countries, split by destination mobile network and
landline, with caller line/home country and visited network specified. Include
activation and monthly line fees, data, outgoing/incoming voice, SMS, roaming,
billing increments, commitments, and taxes. Ask explicitly about remote first
activation, permanent roaming eligibility, prepaid caps, usage delay, supported
devices, and test SIMs. No supplier has yet established a complete price or
production-ready coverage for DamDam's new requirement.

## Payments and company jurisdiction — 7 September 2026

Global customer reach and merchant incorporation are separate eligibility
questions. Paystack can accept international cards for eligible merchants,
but its international-payment policy explicitly excludes data resellers and
instant-value businesses such as airtime sellers. DamDam's proposed model
overlaps these categories. Do not assume international approval or an exemption
because the eSIM includes voice. Its published merchant onboarding countries
do not include the Isle of Man. Retain Paystack only as a possible local
integration for an eligible entity and product if approved.
https://support.paystack.com/en/articles/2127682
https://support.paystack.com/en/articles/2128898

Stripe explicitly states that businesses based in the Isle of Man are not
supported and cannot sign up as UK businesses on that basis. A UK entity is
a different option requiring genuine eligibility, matching company/banking
information and approval for the actual service. Company registration alone
does not establish payment acceptance, tax treatment, or telecom authorization.
https://support.stripe.com/questions/stripe-availability-for-outlying-territories-of-supported-countries?locale=en-GB
https://stripe.com/legal/restricted-businesses

Payment candidates and exclusions:

- Adyen: first eligibility enquiry candidate. Publishes a mobile top-up case
  study with Ding and includes Isle of Man in its Platforms user-onboarding
  documentation. Platforms user coverage does not establish direct merchant
  onboarding for DamDam; ask explicitly about a new Isle of Man telecom
  merchant, projected volume, minimum invoice, ownership and settlement bank.
  https://www.adyen.com/knowledge-hub/ding
  https://docs.adyen.com/platforms/onboard-users
- Checkout.com: second eligibility enquiry candidate, with an official
  Community Fibre telecom case study. Isle of Man merchant eligibility and
  startup commercial fit are unconfirmed. Customer-country/payment-method
  lists are not evidence of merchant incorporation support.
  https://www.checkout.com/case-studies/community-fibre-improves-broadband-customer-flexibility-by-activating-card-payments
- Braintree: its published fee geography includes Isle of Man, but the AUP
  reviewed lists prepaid phone cards, phone services, and cell phones among
  disallowed categories. Do not treat it as an available telecom replacement
  merely because the jurisdiction is listed.
  https://www.paypal.com/uk/webapps/mpp/enterprise/paypal-braintree-fees
  https://www.paypal.com/uk/legalhub/braintree/acceptable-use-policy

No replacement has been approved or selected. If incorporation is still open,
compare the Isle of Man option against a qualifying UK operating company with
Stripe or another approved processor, considering banking, administration,
actual operations, and professional tax advice. Do not create an extra company
or change jurisdiction solely on assumed processor acceptance.

Proposed payment experience:

- Consumer: purchase a specific plan/top-up, with cards and Apple Pay/Google
  Pay where supported; saved payments and explicit consent for optional renewal.
- Enterprise/government: invoices and bank transfers, with reconciled funds
  or an explicitly approved credit facility before bulk provisioning.
- Service credit, if offered, is usable for DamDam connectivity. Do not add
  peer-to-peer transfers or general-purpose cash-out to the initial product;
  disclose prepaid service credit clearly to the processor.
- Record order currency, gross amount, tax, fees, settlement currency and FX
  separately. Do not equate prices displayed to customers with settlement
  currencies or Telnyx's invoice currency.

Repository implementation shape:

- Reuse the PaymentProvider protocol, but replace amount_ngn-only structures
  with explicit currency and correctly scaled amounts; generalize processor
  enums and API/mobile contracts currently limited to Paystack/Flutterwave.
- Keep order/payment states separate from eSIM/line activation. Authenticate
  webhook events and match merchant account, provider reference, amount,
  currency and successful captured/paid status before granting service.
- Make payment processing and fulfillment idempotent; reconcile ambiguous
  payment outcomes before presenting another attempt that could double-charge.
- Reconcile refunds, disputes, provider fees, payouts and enterprise bank
  receipts in the ledger. Define already-consumed-service handling explicitly.
- Keep payment integrations separate from Telnyx provisioning and avoid
  replacing the current processor with an unapproved live integration.

A draft provider eligibility enquiry is saved separately in
damdam-payment-provider-enquiry.md. It has not been sent.

## Yadaphone comparison evidence — 7 September 2026

Yadaphone provides prepaid browser-to-phone calling: the recipient answers on
an ordinary phone. Its current website footer credits Twilio. Its founder,
Denis Yurchak, also named Twilio, Telnyx, and Vonage in Product Hunt comments
from approximately 2025 and described choosing providers by region/conditions.
This is public first-party evidence of reported use, not an independent audit
of current routing or provider traffic shares.
https://www.yadaphone.com/en-US/call-from-laptop
https://www.yadaphone.com/en-US/privacy
https://www.producthunt.com/products/yadaphone

The user clarified that the pricing comparison is for calls TO NIGERIA.
Yadaphone's US-to-Nigeria and Saudi-to-Nigeria pages advertise $0.46/min for
mobile and landline calls. Twilio's Nigeria Voice API page lists $0.2303/min
for Nigeria/Globacom and $0.2349/min for Nigeria-Mobile, plus $0.004/min for a
browser/app leg when used. These are browser/API benchmarks, not quotes for
voice-and-data carrier eSIM service or Yadaphone's private supplier costs.
https://www.yadaphone.com/en-US/call/nigeria/from/united-states
https://www.yadaphone.com/en-US/call/nigeria/from/saudi-arabia
https://www.twilio.com/en-us/voice/pricing/ng

No verified current Telnyx Nigeria destination rate was retrieved publicly.
Its support guidance directs customers to account international rate decks.
The Mobile Voice carrier/roaming charges must also be included, so a SIP-only
rate would not establish the carrier eSIM price even if available.
https://support.telnyx.com/en/articles/1130664-countries-that-telnyx-offers-termination-in

No independently established global quality winner was found. Evaluate actual
native calls on supported physical devices/networks: setup delay, audio, drops,
DTMF, correct caller ID, inbound reachability, data coexistence, and billed cost.

## Stable core

Retain React Native, FastAPI, PostgreSQL, Redis/Celery, and the Next.js operations
dashboard. Start with one backend deployment and clearly bounded modules.

Core responsibilities:

- Identity, organization memberships, roles, and account access.
- Catalog, coverage, eligibility, and immutable price quotes.
- Orders, payment records, refunds, and a transaction ledger.
- eSIM provisioning, installation state, top-ups, and usage reconciliation.
- Carrier line activation, number lifecycle, voice eligibility, origin/destination
  rates, carrier credit/caps, usage reconciliation and settlement.
- Notifications, support operations, audit records, and monitoring.

An eSIM profile has a different lifecycle from the plan purchased for it. A plan
purchase must not inherently create a new eSIM; reuse depends on the supplier's
capabilities. A phone line is separate from a verified outbound caller ID.

Order/payment state is separate from provisioning and activation state. A paid
order can still be awaiting provisioning. Unknown supplier outcomes must be
reconciled before purchasing through another supplier.

Model customer, device, eSIM profile, product/coverage, order, service entitlement,
usage record, and financial transaction separately. Carrier-backed phone lines
are part of the initial scope. Recurring subscriptions can extend it later.

Use individual identities with organization memberships rather than shared
organization passwords. Record the paying account separately from the service
recipient. Scope organization resources, ledger entries, background jobs, and
reports consistently, including authorization for every resource lookup.

## Optional modules

Potential additions: app/browser VoIP with verified external caller ID,
recurring memberships, additional devices, referrals, reseller distribution,
enterprise SSO, managed-device deployment, PBX/SIP integrations, and a call assistant.
These are roadmap examples, not initial-release commitments. Enterprise account
management is an initial product module, sharing the core services above.

Each module owns its routes, tables, jobs, UI entries, permissions, and tests.
Shared contracts expose account identity, billing, service entitlements, and
notifications. Modules can react to durable events such as payment confirmed,
eSIM provisioned, usage threshold reached, or call completed; handlers tolerate
duplicate deliveries and can be replayed safely.

Backend capability checks and entitlements control availability, with matching
mobile navigation. Disabling a module must also stop new jobs and reject its
mutating API operations appropriately. Feature flags alone do not provide this
separation.

Provider adapters are distinct from product modules. Data-only suppliers can
serve optional data plans. Carrier suppliers must implement compatible eSIM,
line/number, voice, billing, and roaming contracts as a coherent product.
Do not assume one supplier can add native voice to another supplier's data SIM.
Every adapter declares actual
coverage, top-up, reuse, usage, and calling capabilities. Switching providers
can require migration, native SDK changes, and fresh validation.

This is developer extensibility. New native mobile features can require a new
app release; it is not a promise of arbitrary runtime plugins.

## Changes to the existing repository

- Amend the product, API, data model, mobile, security, and release documents to
  replace the Hajj-first scope with the agreed consumer and enterprise scope.
- Remove family/check-in/SOS screens, routes, workers, notification dependencies,
  permissions, and release gates that belong exclusively to the removed scope.
  Inspect any deployed data before designing the retirement migrations.
- Generalize operator/manifest distribution into enterprise people imports and
  bulk allocation. The current model already defines enterprise and government
  organization types, but dashboard authentication only accepts HTO operators
  and stores a password on the organization. Replace that access model with
  individual staff memberships and roles; adapt routes, terminology, onboarding,
  and approval rules, including the HTO licence requirement.
- Keep internal cross-customer support and supplier operations separate from
  each organization's self-service dashboard.
- Replace Nigerian-only signup/dial validation, Saudi-default product behavior,
  and Naira-only pricing assumptions according to supported launch markets.
- Decouple data and voice balances, plan validity, eSIM lifecycle, and account
  identity. Support country and regional coverage without storing a customer's
  single destination as the basis for every purchase.
- Replace the initial app-dialer journey with carrier line setup/management;
  preserve reusable calling code only as a separate future app-VoIP module.
  Add line/number provisioning, carrier credit enforcement, origin/destination
  tariff models, and usage reconciliation. The current Telnyx WebRTC integration
  is not an implementation of Telnyx Mobile Voice.
- Finish navigation and supplier usage reconciliation, repair CI, then deploy
  staging and produce signed mobile builds.

## Release proof

One supported customer can buy a supported destination plan, install it on a
physical device, use mobile data, make a native-dialer call to Nigeria with
DamDam closed, receive a call where included, see
accurate usage/charges, top up, obtain support, and recover their account.

An organization administrator can invite a colleague with restricted access,
bulk-provision and assign plans, fund employee calls, see reconciled spend, and
offboard a member. Prove that another organization cannot access any of those
resources. Prove concurrency-safe purchases and the carrier's agreed spending
enforcement; do not claim hard voice caps from delayed usage records alone.

Validate declined/duplicate payments, delayed or ambiguous provisioning,
installation failures, network loss during calls, stale usage, insufficient
credit, expired sessions, and supplier outages. Operate monitoring, tested
backups/restoration, refunds, and a reproducible release/rollback process.

Use staged regional rollout and measurable network tests. Worldwide customer
signup, destination data coverage, outbound calling destinations, and phone
number availability are four separate supported-market decisions.
