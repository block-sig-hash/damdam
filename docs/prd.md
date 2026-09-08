# Product Requirements Document

> **Current scope:** the September 2026 reset in §10 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

# DamDam — Nigerian Traveler Connectivity Platform
# Version: 0.1 (MVP)
# Status: DRAFT
# Date: July 2026
# Author: Ibrahim Adamu
# Reviewers: [TBD — Commercial Co-Founder]

---

## 1. Product Overview

DamDam is a mobile application for Nigerian travelers that bundles
three services currently purchased separately: prepaid eSIM data
(active as soon as they land), verified outbound calling that
displays their real Nigerian number to recipients, and a
lightweight group safety layer that lets tour operators and family
members track pilgrim welfare without a live call.

The MVP targets Nigerian Hajj and Umrah pilgrims traveling to
Saudi Arabia, distributed through NAHCON-licensed Hajj Tour
Operators (HTOs) who bundle DamDam packages into their existing
pilgrim packages. All purchases are priced and paid in Naira via
local payment rails (Paystack). The product ships as a single
React Native codebase for **both iOS and Android** at MVP — this
is a deliberate scope decision (revised from an earlier
Android-only plan) and has real implications for the eSIM
activation flow, covered in §5.4 and the mobile frontend spec.

---

## 2. Goals and Non-Goals

**MVP Goals**
- G1: Enable a Nigerian Hajj pilgrim to purchase a connectivity
  package in Naira before departure and have data and calling
  available within minutes of landing in Jeddah
- G2: Enable a pilgrim to call any Nigerian mobile number from
  Saudi Arabia with their real Nigerian number showing as caller ID
- G3: Enable a pilgrim to send a check-in or SOS that reaches their
  HTO operator and a nominated family contact even under poor
  network conditions
- G4: Enable an HTO operator to provision packages for an entire
  flight manifest from a web dashboard without individual pilgrim
  action
- G5: Generate first revenue before Hajj 2027 (target: May 2027)
- G6: Ship on both iOS and Android at MVP launch

**Non-Goals for MVP (explicitly out of scope)**
- NG1: Real-time live location tracking (check-in is manual, not
  continuous)
- NG2: Family companion mobile app (family receives WhatsApp
  notifications only)
- NG3: China or any destination beyond Saudi Arabia
- NG4: Enterprise or government sales dashboard
- NG5: In-app add-on purchases (handled via WhatsApp support for
  MVP)
- NG6: Subscription pricing model (per-package only for MVP)
- NG7: Silent/automatic eSIM activation (one-tap notification-
  triggered activation only; true silent switching is not possible
  on either platform — see §5.4)
- NG8: Multi-language support (English only for MVP)
- NG9: Umrah-specific features distinct from Hajj (same product,
  different package duration)

---

## 3. User Types

### 3.1 Pilgrim
The primary end user. A Nigerian Muslim traveling to Saudi Arabia
for Hajj or Umrah. Device profile: mid-range Android (Tecno,
Infinix, Samsung Galaxy A-series) is the majority case given
Nigeria's ~91% Android market share, but iOS users (iPhone owners,
skewing toward higher income or diaspora-connected pilgrims) are a
real minority segment worth supporting at MVP. Likely first or
second international trip. May have limited comfort with
app-based purchases. Will have been directed to DamDam by their
HTO. Speaks English and at least one Nigerian language. May be
40–70 years old.

**Capabilities:**
- Purchase a connectivity package
- Download and activate an eSIM
- Make outbound calls from the app
- Send a check-in ping
- Trigger an SOS alert
- View their package status (data remaining, minutes remaining)
- Contact support via WhatsApp

**Cannot:**
- Access other pilgrims' data
- Modify their package after purchase
- Create an account without a valid Nigerian phone number (used
  for CLI verification)

### 3.2 HTO Operator
Staff at a NAHCON-licensed Hajj Tour Operator. Uses the web
dashboard (not the mobile app). Technically semi-literate —
comfortable with spreadsheets, WhatsApp, and basic web tools.
Manages batches of 20–500 pilgrims per flight.

**Capabilities:**
- Log in to the web dashboard
- Upload a flight manifest (CSV with pilgrim names and Nigerian
  phone numbers)
- Bulk-provision packages for the entire manifest, or a selected
  subset (mixing individual-tier and Family-tier group purchases
  within one manifest — see data-model.md §6.5)
- View check-in status for all pilgrims on their manifest
- Receive SOS alerts with pilgrim details
- Download a provisioning report
- Purchase packages in bulk at the wholesale rate

**Cannot:**
- Access pilgrims from other HTOs
- Modify individual pilgrim packages once provisioned
- Access financial data beyond their own account

### 3.3 Family Contact
A family member nominated by the pilgrim during onboarding. Not
an app user. Receives WhatsApp messages only — check-in
confirmations and SOS alerts. Nigerian phone number. No account,
no login.

Cannot do anything in the system. Is a notification recipient only.

### 3.4 System Administrator
Internal DamDam team. Access to all data via four scoped admin
screens (see frontend-dashboard.md §9.1, Screens 13–17). Manages
HTO account approvals, manifest payment confirmation, failed
notification retries, and device compatibility monitoring.

---

## 4. User Stories & Acceptance Criteria

User stories follow the format: "As a [user type], I want to
[action] so that [outcome]." Each story is tagged with a priority:
**[P0]** = MVP blocker · **[P1]** = MVP important · **[P2]** = MVP
nice-to-have.

### 4.1 Account Creation — Path A (Pilgrim direct)

**US-01** [P0] — As a Pilgrim, I want to download the app and sign
up using my Nigerian phone number so that I can create an account
without needing an invitation.
- AC-01.1: App accepts only valid Nigerian phone numbers (070x,
  080x, 081x, 090x, 091x, 11 digits)
- AC-01.2: App rejects international numbers at entry
- AC-01.3: App sends a 6-digit OTP via SMS within 10 seconds
- AC-01.4: OTP expires after 10 minutes
- AC-01.5: 3 OTP attempts allowed before a 60-second lockout
- AC-01.6: On successful OTP entry, account is created and user
  is logged in
- AC-01.7: If the number already has an account, direct to login
- AC-01.8: If the primary OTP provider (Termii) has not returned
  a delivery confirmation within 180 seconds (config value:
  `OTP_FAILOVER_THRESHOLD_SECONDS`), the system automatically
  retries via the secondary OTP provider (Twilio Verify) without
  user action or visible error
- AC-01.9: UI shows a "Sending your code..." state after 10
  seconds and offers a manual resend option from 30 seconds,
  independent of the automatic provider failover threshold

**US-02** [P0] — As a Pilgrim, I want to set a 4-digit PIN after
phone verification so that my account is protected without needing
a password I might forget.
- AC-02.1: PIN must be 4 digits, not sequential or repeated
- AC-02.2: PIN entry is masked, entered twice to confirm
- AC-02.3: PIN unlocks the app on subsequent opens
- AC-02.4: 5 failed attempts → 30-minute lock, OTP-based recovery
  available immediately

**US-03** [P0] — As a Pilgrim, I want to nominate a family
contact's WhatsApp number during setup so that they receive my
check-ins and SOS alerts without needing to install the app.
- AC-03.1: Pilgrim enters a Nigerian phone number for the family
  contact
- AC-03.2: System sends a WhatsApp notification to the nominated
  number; no confirmation required from them
- AC-03.3: Pilgrim can update the nominated number at any time
- AC-03.4: One family contact per pilgrim for MVP

### 4.2 Account Creation — Path B (HTO-initiated)

**US-04** [P0] — As an HTO Operator, I want to create a business
account on the web dashboard so that I can manage packages for my
pilgrims.
- AC-04.1: Registration requires business name, operator name,
  email, phone number, NAHCON licence number
- AC-04.2: Licence number recorded but manually reviewed (not
  programmatically validated) for MVP
- AC-04.3: Email verification required before account activation
- AC-04.4: New accounts pending admin approval (target: 24 hours)
- AC-04.5: Operator notified via email + WhatsApp on approval

**US-05** [P0] — As an HTO Operator, I want to upload a CSV
manifest of my pilgrims so that I can provision packages for them
in bulk.
- AC-05.1: CSV only, max 500 rows per upload
- AC-05.2: Required columns: first_name, last_name, phone_number
- AC-05.3: Optional: passport_number, seat_number
- AC-05.4: Every phone number validated (Nigerian format) before
  acceptance
- AC-05.5: Invalid rows flagged with row number + reason; valid
  rows accepted independently (no all-or-nothing)
- AC-05.6: Operator sees a preview before confirming
- AC-05.7: Duplicate phone numbers flagged as warnings, not errors

**US-06** [P0] — As an HTO Operator, I want to select pilgrims from
my manifest and purchase a package tier for them at the wholesale
rate — including forming Family-tier groups — so that I can resell
DamDam as part of my Hajj package.
- AC-06.1: Operator selects a subset of unordered pilgrims from
  the manifest (individuals for a bulk tier, or a pre-grouped
  Family set) — see data-model.md §6.5 for the multi-order model
- AC-06.2: Dashboard shows per-pilgrim wholesale price, total, and
  estimated retail margin
- AC-06.3: Payment is via invoice (bank transfer) for MVP
- AC-06.4: PDF invoice generated and emailed on order confirmation
- AC-06.5: Packages provisioned and activation links sent only
  after DamDam admin manually confirms payment received
- AC-06.6: A manifest may have multiple orders across different
  tiers/groupings; remaining unordered pilgrims stay available for
  a subsequent order

**US-07** [P1] — As a Pilgrim, I want to receive a WhatsApp message
with an activation link from my HTO so that I can activate my
pre-purchased package without paying myself.
- AC-07.1: Message sent within 5 minutes of payment confirmation
- AC-07.2: Includes operator name, tier, deep link (Play Store /
  App Store fallback if app not installed), unique 8-character
  activation code
- AC-07.3: Code is single-use, expires after 30 days
- AC-07.4: New pilgrim: OTP → PIN → package auto-attached via code
- AC-07.5: Existing pilgrim: log in, package attached via code
- AC-07.6: Post-activation experience identical to Path A

### 4.3 Package Purchase — Path A (Direct retail)

**US-08** [P0] — As a Pilgrim, I want to browse available packages
with clear descriptions so that I can choose the right one.
- AC-08.1: All four tiers shown: Starter, Basic, Standard, Family
- AC-08.2: Each shows name, NGN price, data GB, PSTN minutes,
  3 feature bullets
- AC-08.3: "Recommended" badge on Standard
- AC-08.4: Family tier shows a **group-size selector (2–8)** with
  the total price recalculating live as size changes (per
  data-model.md §6.4)
- AC-08.5: "What's included" expandable section
- AC-08.6: Prices reflect whatever Naira value is currently set
  by an admin (§5.9/US-26) — no live per-request FX calculation

**US-09** [P0] — As a Pilgrim, I want to pay in Naira via card,
bank transfer, or USSD so that I do not need a foreign currency
card.
- AC-09.1: Payment web view opens in-app on "Buy now" — Paystack
  by default, Flutterwave if Paystack checkout initialization
  fails (`data-model.md` §6.7); the pilgrim never sees a
  processor choice
- AC-09.2: Supports card, bank transfer, USSD, Opay/Palmpay
- AC-09.3: Success screen shown immediately on payment confirmation
- AC-09.4: Failure reason shown with a "Try again" option
- AC-09.5: Receipt sent via email/WhatsApp within 2 minutes
- AC-09.6: Package activated within 60 seconds of webhook receipt
- AC-09.7: Idempotent on processor reference — duplicate webhooks
  do not double-provision, regardless of which processor was used

### 4.4 eSIM Compatibility and Pre-Departure Preparation

**US-10** [P0] — As a Pilgrim, I want the app to check whether my
device supports eSIM and warn me clearly if it does not so that I
can make alternative arrangements before I travel.
- AC-10.1: On entering the eSIM setup screen, the app checks
  device eSIM capability (platform-specific — see §5.4 for the
  iOS/Android distinction)
- AC-10.2: If supported: proceed to download flow
- AC-10.3: If unsupported: warning modal — *"Your device does not
  appear to support eSIM. You can still use your DamDam package by
  scanning the QR code on a compatible device. Tap Continue to
  download your QR code, or tap Support to get help."*
- AC-10.4: "Continue" proceeds without blocking
- AC-10.5: "Support" opens WhatsApp with a pre-filled order
  reference
- AC-10.6: Warning shown once, not repeated on subsequent opens
- AC-10.7: HTO dashboard flags eSIM-incompatible pilgrims with a
  "Follow up" label

**US-11** [P0] — As a Pilgrim, I want to download my eSIM profile
and receive a QR code before I depart so that I do not need
internet access after landing.
- AC-11.1: Available from purchase, recommended window "2–7 days
  before departure"
- AC-11.2: On supported devices: "Download to device" initiates
  eSIM download via the aggregator API
- AC-11.3: QR code always generated and saveable as a fallback
- AC-11.4: Idempotent — repeated taps issue only one profile
- AC-11.5: Failed downloads queue and auto-retry, with
  notification on success
- AC-11.6: Download status visible to the HTO operator

**US-12** [P1] — As a Pilgrim, I want to see emergency contacts
and key phrases before I depart so I have them without needing
internet, even without a map.
- AC-12.1: Emergency essentials shown on the same pre-departure
  screen as eSIM QR/download (§5.4)
- AC-12.2: Includes the HTO operator's number, DamDam support
  WhatsApp, and a short set of key Arabic phrases (help, thank
  you, where is, I don't understand, I need a doctor)
- AC-12.3: Content is bundled directly in the app, not downloaded
  separately — always available offline, zero data cost, no
  download step, no map SDK or content-pack table needed
- AC-12.4: The same content is also reachable from the SOS screen
  for quick reference during an actual emergency, not just
  pre-departure

**Scope note:** This story originally covered full offline maps
(Haram/Mina/Arafat POIs, a ≤50MB downloadable pack, in-app
navigation). That was cut deliberately — it's P1, not a stated MVP
goal (G1–G6), and largely redundant once a pilgrim's eSIM data is
active, since their phone's own Maps app already covers wayfinding
better than anything DamDam would build. What's kept is the
narrow slice a phone's OS maps can't provide: emergency contacts
and phrases that work with zero connectivity and zero setup.

### 4.5 Arrival and eSIM Activation

**US-13** [P0] — As a Pilgrim, I want to receive a prompt to
activate my eSIM with minimal friction after landing so that I
have data within minutes of arrival.
- AC-13.1: Geofencing (150km radius, Jeddah) triggers a push
  notification on entry, **where location permission is granted**
- AC-13.2: Notification: *"You've arrived in Saudi Arabia. Tap to
  activate your DamDam data — takes 30 seconds."*
- AC-13.3: Tap deep-links to the activation screen
- AC-13.4: **Android with carrier-privilege support:** single-tap
  in-app profile switch with one system confirmation dialog
- AC-13.5: **All iOS devices, and Android devices without
  carrier-privilege support:** routes to a step-by-step manual
  guide (§5.4 — iOS has no public API for programmatic eSIM
  switching; this is the primary path for every iOS pilgrim, not
  a fallback)
- AC-13.6: Home screen shows "Saudi Arabia data — active" with
  remaining data once activated
- AC-13.7: If geofencing fails or permission denied: a persistent
  "Activate eSIM" banner appears from 7 days before the recorded
  departure date — this is the reliable primary trigger; geofence
  is a bonus layer only

### 4.6 In-Country Usage

**US-14** [P0] — As a Pilgrim, I want to make an outbound call
showing my real Nigerian number so that my family picks up.
- AC-14.1: CLI verification is a dedicated one-time flow, separate
  from account login OTP — phone-possession proof (Telnyx Verified
  Numbers) plus explicit CLI consent, before a number can be used
  as caller ID — see §5.5's CLI-verification amendment paragraph
- AC-14.2: Dial pad + device contacts picker
- AC-14.3: Calls route over the eSIM data connection (VoIP)
- AC-14.4: Recipient sees the pilgrim's verified Nigerian number
- AC-14.5: Call quality indicator shown during the call
- AC-14.6: Dropped connectivity → graceful "Call ended —
  connectivity lost", not a silent freeze
- AC-14.7: PSTN minutes deducted in real time, balance updated
  within 60 seconds
- AC-14.8: App-to-app calls are free, shown clearly as such
- AC-14.9: Call history shows last 20 calls
- AC-14.10: The verified number is not required to match the
  account's login number — a pilgrim may verify possession of any
  Nigerian mobile number as CLI, independent of which number they
  signed in with
- AC-14.11: Revoking consent, reporting a lost SIM, or an admin
  suspension immediately prevents new calls using that CLI; no
  in-flight call is force-terminated by a revocation

**US-15** [P0] — As a Pilgrim, I want to send a check-in with a
single tap so that my HTO and family know I am safe, even with
poor connectivity.
- AC-15.1: "I'm okay" button, single tap, no confirmation dialog
- AC-15.2: Timestamp + GPS (if permitted) recorded on tap
- AC-15.3: Transmitted within 5 seconds if connected
- AC-15.4: If offline: queued locally, retried every 30s, UI shows
  "Check-in queued, will send when connected"
- AC-15.5: HTO dashboard updates last-seen status on success
- AC-15.6: Family contact receives WhatsApp: *"[Name] checked in
  safely at [time]. All is well."*
- AC-15.7: Includes a Google Maps link if location available
- AC-15.8: Pilgrim sees "Check-in sent" confirmation
- AC-15.9: Rate-limited to one per 15 minutes
- AC-15.10: If the WhatsApp notification to the family contact
  fails or does not confirm delivery within 60 seconds, an SMS
  with equivalent content is sent automatically as a fallback

**US-16** [P0] — As a Pilgrim, I want to trigger an SOS that
immediately notifies my HTO and family with my location so that I
can get help in an emergency.
- AC-16.1: Red "SOS / Emergency" button, visually distinct from
  check-in
- AC-16.2: 3-second press-and-hold with visual countdown
- AC-16.3: On confirmed SOS: stored locally first, then server
  notified (queued if offline); HTO gets push + dashboard alert +
  email + WhatsApp; family gets an URGENT WhatsApp message with
  location link and the HTO's direct number
- AC-16.4: "SOS sent — help is coming" screen with the HTO's
  number as a native-dialer "Call now" button
- AC-16.5: SOS cannot be accidentally cancelled — separate
  "Cancel SOS" button with confirmation
- AC-16.6: Cancellation sends a follow-up notification to both
  channels
- AC-16.7: No rate limit on SOS

**US-17** [P1] — As a Pilgrim, I want to see my remaining data and
minutes on the home screen so that I know when to top up.
- AC-17.1: Persistent status cards for data and minutes
- AC-17.2: Updates within 60 seconds of a usage event
- AC-17.3: Yellow warning below 20% data / 5 minutes voice
- AC-17.4: Red warning at zero
- AC-17.5: Add-ons handled via WhatsApp support for MVP (no
  in-app purchase flow yet)
- AC-17.6: Values remain visible offline (last cached)

### 4.7 HTO Operator — Dashboard Experience

**US-18** [P0] — As an HTO Operator, I want to see the check-in
status of all my pilgrims at a glance.
- AC-18.1: Default view sorted by risk — unresolved SOS first,
  then stale check-ins, then alphabetical
- AC-18.2: Each row: name, phone, tier, eSIM status, last check-in
- AC-18.3: >24h since check-in → amber highlight
- AC-18.4: Unresolved SOS → red highlight, pinned to top
- AC-18.5: Auto-refresh every 60s + manual refresh
- AC-18.6: Filter by manifest
- AC-18.7: Search by name or phone

**US-19** [P0] — As an HTO Operator, I want immediate alerts on
any SOS so that I can respond without checking the dashboard.
- AC-19.1: Browser push notification
- AC-19.2: Email within 60 seconds
- AC-19.3: WhatsApp message
- AC-19.4: All three fire regardless of dashboard session state
- AC-19.5: Operator can mark "Resolved", clearing the highlight
- AC-19.6: Resolved SOS sends no further notifications

**US-20** [P1] — As an HTO Operator, I want to download a
provisioning report for my own records and NAHCON compliance.
- AC-20.1: CSV download
- AC-20.2: Per-pilgrim: name, phone, tier, purchase date, eSIM
  status, check-in count, SOS events
- AC-20.3: Filterable by manifest and date range
- AC-20.4: Generated within 30 seconds for manifests up to 500 rows

### 4.8 Family Contact Experience

**US-21** [P0] — As a Family Contact, I want a WhatsApp message
when my pilgrim checks in so I know they're safe without calling.
- AC-21.1: Sent from a consistent DamDam WhatsApp Business number
- AC-21.2: Plain English, no jargon
- AC-21.3: Delivered within 60 seconds of server receipt

**US-22** [P0] — As a Family Contact, I want a WhatsApp message
when my pilgrim triggers an SOS so I know immediately.
- AC-22.1: Message begins with "URGENT:"
- AC-22.2: Includes the HTO operator's direct phone number
- AC-22.3: If the WhatsApp SOS notification to the family contact
  fails or does not confirm delivery within 60 seconds, an SMS
  with equivalent content is sent automatically as a fallback

### 4.9 Authentication and Session Management

**US-23** [P0] — As a Pilgrim, I want my session to stay active so
I don't have to log in repeatedly, especially without internet.
- AC-23.1: Session tokens stored in platform secure storage
  (Android Keystore / iOS Keychain)
- AC-23.2: Session persists 30 days of inactivity
- AC-23.3: PIN required after 5 minutes backgrounded, validated
  locally (no network call needed)
- AC-23.4: Full re-authentication only on a new device or after
  30 days
- AC-23.5: Offline features (maps, SOS queue, PIN unlock) work
  without any server connection

### 4.10 System-Level Stories

**US-24** [P0] — As the System, I want to queue check-in and SOS
events locally and transmit on reconnect so safety data is never
lost to network congestion at Mina or Arafat.
- AC-24.1: Local write before any network attempt
- AC-24.2: Background retry every 30s while queued
- AC-24.3: Not removed from queue until server 200 response
- AC-24.4: Queue persists across app restarts/reboots
- AC-24.5: Home screen shows "X event(s) waiting to send"

**US-25** [P0] — As the System, I want to prevent duplicate
package provisioning.
- AC-25.1: Payment webhook references checked for idempotency,
  regardless of which processor (Paystack or Flutterwave) issued
  the transaction — see `data-model.md` §6.7
- AC-25.2: HTO activation codes single-use
- AC-25.3: One active package per destination per trip period
- AC-25.4: Duplicate attempts logged for admin review, no visible
  user-facing error

**Implementation note (AC-25.3, finalized post-MVP-scoping
discussion):** "one active package per trip period" is implemented
as **chaining, not blocking**. Each `pricing_tiers` row carries a
`validity_days` value (MVP defaults: 7 / 15 / 30 days for
base/medium/high tiers). A pilgrim buying a new package while one is
already active does not get rejected or produce a second
concurrently-active package — the purchase immediately supersedes
the current package: the new package's allowance
(`data_gb_remaining`/`pstn_minutes_remaining`) becomes usable right
away, its remaining balance is rolled forward from the superseded
package (nothing paid-for is stranded), and its `expires_at` is
computed from the *superseded package's expiry*, not from the
purchase moment — i.e. validity periods stack back-to-back rather
than overlapping. The superseded package moves to a new terminal
status (`PackageStatus.SUPERSEDED`, distinct from `EXPIRED`, which
still means "ran out naturally"). This keeps "exactly one `ACTIVE`
package per user at a time" true as an invariant, so nothing
elsewhere that reads "the active package" (e.g. PSTN balance lookup
in `app/voice/service.py`) needed to change.

Top-ups (AC-17.5's WhatsApp-support-manual add-ons, no in-app
purchase flow yet) do **not** get their own validity window under
this design — once built, a top-up should add allowance to the
current active package and inherit its existing `expires_at`, not
extend or reset it. That's a forward-looking data-model note only;
no top-up purchase flow exists to build against yet.

For the genuine-mistake case (pilgrim accidentally double-purchases,
wants one reversed): an admin-only `cancel` action sets a package to
`CANCELLED` and writes an audit-log entry. It deliberately does
**not** attempt automatic balance/chain reversal, refund, credit, or
reactivation of a superseded package — none of that infrastructure
exists yet (confirmed: no refund method anywhere in `app/payments/`,
and `api-spec.md` §7.13 already excludes refund processing from the
MVP admin UI, treating corrections as a direct database action for
now). A smarter automatic reversal is real future work, but belongs
alongside the payment-abstraction refund capability
`scaling-infrastructure.md`'s multi-processor design already
anticipates building post-MVP — not invented ad hoc here.

**US-26** [P1] — As an Admin, I want to manually update Naira
package prices from the dashboard so that pricing can be adjusted
when the exchange rate moves, without a live FX API dependency or
a daily automated job.
- AC-26.1: Admin screen shows the current Naira price per tier,
  editable
- AC-26.2: Updated price takes effect immediately for new
  purchases; in-progress checkouts already underway are unaffected
- AC-26.3: Price change requires confirmation showing the %
  change from the current price — a lightweight version of the
  original guardrail, surfaced to the admin rather than blocking
  automatically
- AC-26.4: Every price change is logged (admin, timestamp, old
  value, new value) for audit purposes
- AC-26.5: No live FX API dependency, no scheduled job — this is
  a fully manual, on-demand action

**Scope note:** This story originally specified a fully automated
daily FX-indexed pricing engine (a 09:00 WAT cron job hitting a
currency data API, a 5% day-over-day guardrail, live NFEM
tracking). That was scaled down deliberately — it's P1, and the
Naira has been comparatively stable through 2026 under CBN's
reformed NFEM framework (roughly 1-2% monthly movement in recent
months), making a standing external API dependency and cron
infrastructure disproportionate to the actual risk right now. The
underlying reason this exists at all is real and unchanged —
DamDam's costs are USD-denominated (Telnyx, Termii/Twilio, the
eSIM aggregators) while revenue is fixed-Naira, and HTOs may sell
packages months before the actual Hajj travel and vendor billing —
so pricing still needs a way to move with the exchange rate. It
just doesn't need to move automatically every single day to do
that job. If the Naira becomes meaningfully more volatile later,
revisit automating this — the manual version doesn't foreclose
that, it just isn't building it before it's needed.

---

## 5. Feature Specifications

Each module maps to the user stories above. Format: Description →
Trigger → Flow → Dependencies → Failure modes.

### 5.1 Authentication & Identity
**Maps to:** US-01, US-02, US-04, US-23

Phone-number-based identity for pilgrims (OTP + PIN); email-based
for HTO operators (email + password + admin approval gate).

**Flow — Pilgrim:** Phone entry → Termii OTP (Redis-cached,
10-min TTL) → JWT issued on success → PIN set (bcrypt hash, never
transmitted post-set).

**Flow — HTO Operator:** Email + password registration → email
verification link (24h expiry) → `pending_approval` state → manual
admin review of NAHCON licence → approved, notified via email +
WhatsApp.

**Dependencies:** Termii (primary OTP provider — direct-carrier
connections and lower cost for Nigerian numbers, vs. Twilio's
per-verification fee and aggregator routing into Nigeria), Twilio
Verify (secondary OTP provider), Redis, Postgres, Resend.

**Failure modes:** OTP delivery failure → 30s cooldown, max 3
resends/hour across both providers combined; if the primary
provider (Termii) has not returned a delivery confirmation within
180 seconds (config value: `OTP_FAILOVER_THRESHOLD_SECONDS`) the
system automatically retries via the secondary provider (Twilio
Verify), transparent to the user — the UI shows a "Sending your
code..." state after 10 seconds and offers a manual resend option
from 30 seconds, so the automatic failover threshold can be tuned
later based on real delivery-latency data without needing a UX
change; total OTP-provider outage (both down) → account creation
and CLI verification blocked; PIN lockout → 30-min lock, OTP
recovery available immediately once a provider is reachable.

**Configuration note:** Provider primary/secondary designation and
the failover threshold are held as configuration
(`OTP_PROVIDER_PRIMARY` / `OTP_PROVIDER_SECONDARY` /
`OTP_FAILOVER_THRESHOLD_SECONDS`), not hardcoded, so they can be
adjusted post-launch based on observed delivery reliability without
a logic rewrite.

### 5.2 HTO Manifest & Bulk Provisioning
**Maps to:** US-05, US-06, US-25

CSV upload → row-level validation → pilgrim selection (individual
or Family group) → tier selection → invoice → manual payment
confirmation → provisioning → activation dispatch.

**Flow:** Upload parsed with per-row validation → preview shown →
manifest confirmed → operator selects an unordered subset →
optionally groups into Family sets (`family_group_id`) → places
an order (tier + selection) → invoice generated → **admin manually
confirms payment** (the one deliberate manual step in the pipeline)
→ background job provisions accounts + activation codes for that
order's pilgrims → WhatsApp dispatch (rate-limited ~80 msg/min). A
manifest supports multiple orders across different tiers/groupings
(data-model.md §6.5).

**Dependencies:** Postgres, Redis (job queue), WhatsApp Business
API, PDF generation, manual admin action.

**Failure modes:** CSV >500 rows rejected at upload; WhatsApp
partial-send failures logged with manual resend; provisioning job
is idempotent per row, safe to re-run on crash.

### 5.3 Package Purchase & Payment (Path A — Retail)
**Maps to:** US-08, US-09, US-25, US-26

In-app Naira checkout via Paystack, with an automatic Flutterwave
fallback if Paystack's checkout initialization fails or times out
(`data-model.md` §6.7). The fallback is backend-only and invisible
to the pilgrim — there is no "choose your payment provider" screen.

**Flow:** Tier + (if Family) group size selected → backend attempts
Paystack checkout initialization; on failure, falls back to
Flutterwave automatically → inline web view opens with the
resulting `checkout_url` (generic, per `api-spec.md` §7.3) and a
generated UUID reference → webhook to `/webhooks/paystack` or
`/webhooks/flutterwave` depending on which processor was used →
signature verified (HMAC SHA512 for Paystack, verif-hash for
Flutterwave) → idempotency check on `processor_reference` →
package activated → receipt dispatched.

**Dependencies:** Paystack (primary), Flutterwave (automatic
fallback only, per `data-model.md` §6.7), Postgres, Resend,
WhatsApp Business API.

**Failure modes:** Webhook delay → app polls
`/orders/{reference}/status` every 10s, capped at 5 min before
"Contact support"; duplicate webhook → no-op, still returns 200;
processor-side failure on the fallback (Flutterwave) too → surfaced
directly to the pilgrim, no further retry — this is the one case
where both processors being unavailable simultaneously isn't
architected around, since it's judged low-probability enough not
to warrant a third processor at MVP.

**Configuration note:** Processor primary/secondary designation
(Paystack primary, Flutterwave secondary) is held as configuration
(`PAYMENT_PROCESSOR_PRIMARY` / `PAYMENT_PROCESSOR_SECONDARY`), not
hardcoded — consistent with the OTP and eSIM vendor pattern — so
the order, or a future third processor, can be adjusted post-launch
based on observed success rates, settlement speed, or fee changes,
without a logic rewrite. This doesn't change the idempotency/webhook
behavior above, which already works correctly regardless of which
processor is primary at any given time.

### 5.4 eSIM Provisioning & Activation
**Maps to:** US-10, US-11, US-13

Device compatibility check → aggregator issuance → QR fallback →
platform-appropriate activation trigger.

**This is the section most affected by dual-platform scope.**
Device capability check differs meaningfully by platform:

- **Android:** `EuiccManager` API can check `hasEuicc()`. Some
  devices additionally support carrier-privilege-based programmatic
  profile switching if the eSIM vendor grants carrier-privilege
  metadata (an eSIM Access-style integration) — this is a one-tap,
  single-confirmation-dialog flow where available.
- **iOS:** There is **no public API for programmatic eSIM
  installation or switching** on iOS. Every iOS pilgrim — regardless
  of whether their specific iPhone model supports eSIM at the
  hardware level — is routed to the manual Settings-based guide.
  eSIM hardware support on iOS is effectively iPhone XS and later;
  the app should detect device model (not a capability API, since
  none exists) to decide whether to show the compatibility warning
  or the manual guide.

  **Implementation note (US-10):** rather than a hand-maintained
  known-supported-models list — which needs a yearly update per
  iPhone release and is a real source of transcription error to get
  right from memory — this is implemented as a generation-number
  threshold: `getDeviceId()` returns iOS's hardware identifier in
  the form `iPhoneN,M`, and iPhone XS (the oldest eSIM-capable
  model) is generation 11, so `N >= 11` is treated as supported.
  Same capability check as a models list would give, without the
  maintenance burden.

**Flow:**
1. Compatibility check (platform-specific, as above); result
   logged to `device_compatibility_log`
2. Unsupported → warning modal (AC-10.3), QR-only path
3. Aggregator issuance attempted against the primary vendor
   (Monty Mobile); on issuance failure (a real error response or
   timeout, not merely slow), the system automatically retries
   against the secondary vendor (eSIM Access), then the tertiary
   (1Global), before falling to the retry-with-backoff-then-
   admin-queue behavior below. Each attempt is logged to
   `device_compatibility_log` with the vendor used, so admin can
   see which vendor actually served a given pilgrim's profile.
   Issues: `iccid`, `activation_code` (LPA string), QR image URL.
4. Activation trigger: **primary** is the date-based banner (7
   days pre-departure, no permission required); **secondary** is
   the opt-in geofence push
5. Android carrier-privilege devices: in-app one-tap switch.
   **All other devices (all iOS, non-privileged Android):**
   device-model-specific manual guide with screenshots

**Dependencies:** Monty Mobile (primary aggregator,
`ESIM_VENDOR_PRIMARY`), eSIM Access (secondary aggregator,
`ESIM_VENDOR_SECONDARY`), 1Global (tertiary aggregator,
`ESIM_VENDOR_TERTIARY`) — vendor ranking held as configuration,
not hardcoded, since relative pricing, coverage, and reliability
across the Nigeria/Saudi Arabia corridor are expected to shift as
real usage data comes in. Also: Android `EuiccManager`, Firebase
Cloud Messaging (push, cross-platform via React Native Firebase),
Android Geofencing API / iOS Core Location region monitoring.

**Failure modes:** Single-vendor issuance failure → automatic
cascading fallback through the ranked list above (Monty Mobile →
eSIM Access → 1Global), not just retry against the same vendor;
all three vendors failing → retried with backoff, admin-queued
after 3 attempts; device-specific download failure → QR always
available as universal fallback; geofence non-fire → date-based
banner is the reliable primary path on both platforms.

**Content production note:** The manual activation guide needs
device-specific screenshot walkthroughs for the top Android models
by Nigerian market share (Tecno, Infinix, itel, Samsung Galaxy A)
**and** for the standard iOS Settings flow (fewer variants needed
here since iOS's eSIM settings UI is consistent across supported
iPhone models). This is a content workstream, not just engineering
— scope into the build timeline explicitly.

### 5.5 Verified Caller ID & Voice Calling
**Maps to:** US-14

One-time CLI ownership verification, then in-app VoIP calling
(WebRTC over data) displaying the verified number for
PSTN-terminated calls, built on **Telnyx** as the primary voice
vendor (selected at Phase 0 per §6, based on PSTN termination
rates for the Nigeria/Saudi Arabia corridor) through a thin
`VoiceProvider` abstraction (`initiate_call`, `set_caller_id`,
`handle_webhook`) rather than a direct SDK integration, so a
future vendor migration or BYOC architecture change doesn't
require rewriting the calling or billing logic.

**Flow:** OTP to the pilgrim's registered number (reuses login
number from §5.1, no separate entry) → `verified_cli` flag set →
calling via Telnyx Programmable Voice (WebRTC + PSTN termination)
→ backend sets the verified number as caller ID on PSTN legs →
DamDam-to-DamDam calls route client-to-client, bypassing PSTN
entirely (free) → Telnyx webhook events drive balance deduction
(5.7).

**Dependencies:** Telnyx Programmable Voice (WebRTC + PSTN
termination), Telnyx webhooks, OTP/CLI verification (§5.1).

**Failure modes:** Token/credential expiry mid-session → SDK
auto-refreshes 5 min before expiry; connectivity drop mid-call →
graceful termination, billed only for connected seconds; Telnyx
outage → calling degrades with an in-app banner while check-in/SOS
continue functioning independently; no automatic failover to a
second voice vendor at MVP — single-vendor risk is accepted
deliberately, since voice is not safety-critical (SOS and check-in
do not depend on the calling stack) and dual-vendor voice routing
is materially more complex to build correctly within the 7-month
timeline.

**Future roadmap note (not MVP):** Once call volume justifies it,
DamDam plans to migrate PSTN termination to a BYOC (Bring Your Own
Carrier) architecture — Telnyx's SIP/API layer stays as the
call-control and WebRTC layer, with PSTN termination routed over
IDT Express's wholesale voice backbone for lower per-minute
termination cost on the Nigeria/Saudi Arabia corridor. This is a
**cost-optimization migration, not a reliability change** — Telnyx
remains the primary carrier; IDT Express becomes a termination-cost
layer underneath it once volume makes wholesale rates outperform
Telnyx's bundled pricing. Tracked as a Phase 2+ infrastructure item
(post-MVP) — not something the `VoiceProvider` abstraction needs to
support on day one, but the abstraction is exactly what makes this
migration low-risk when the time comes.

**CLI-verification amendment (AC-14.1/AC-14.10/AC-14.11):** the
original MVP shortcut — treating the account's login OTP as CLI
ownership proof, since both used the same number — is replaced by a
dedicated CLI verification flow, decoupled from login. Rationale: a
compromised or SIM-swapped login session should not inherit caller-
ID rights with no additional proof, and a pilgrim's login number is
not guaranteed to be the Nigerian number they want family to see.
Phone possession is proven via Telnyx Verified Numbers (separate
from account OTP); activation additionally requires an explicit,
versioned CLI consent capture (see `data-model.md` §6.40's
`CallerIdConsent`). A `VerifiedCallerIdentity` state machine
(`data-model.md` §6.40) replaces the `verified_cli` boolean;
existing users' current `verified_cli=True` state migrates to
`phone_verified`, not `active` — one fresh consent capture is
required before any existing account's calls resume, since consent
was never actually collected under the old shortcut.

NIN identity verification was evaluated as a further activation
requirement (matching the `STRICT_NIN_MSISDN_MATCH_REQUIRED`
capability below) but is **not enabled for this MVP pass** — see
`docs/verified-cli-scoping.md` §4 for the founder/product sign-off
this needs before it's turned on. The identity-provider interface
exists and is wired to a labeled mock so the activation policy is
swappable later without another schema change; no raw NIN is
collected or stored while this stays disabled.

**Action item flagged for founder review:** whether
`NIN_VERIFICATION_ENABLED`/`STRICT_NIN_MSISDN_MATCH_REQUIRED` should
ever be turned on, and on what legal basis, is a KYC/regulatory
decision — not an engineering default. See
`docs/verified-cli-scoping.md` §4.

### 5.6 Check-in & SOS (Offline-First Safety Layer)
**Maps to:** US-15, US-16, US-24

The most safety-critical feature. Built offline-first: every
action written locally before any network attempt.

**Flow — Check-in:** Tap → immediate local SQLite write (`outbox`,
`synced: false`) → optimistic UI confirmation → background sync
(timer + connectivity-change triggered) → server write → WhatsApp
to family + dashboard update to HTO.

**Flow — SOS:** Same local-write-first pattern, with no rate
limit, higher-priority sync (immediate + every 10s vs. 30s), and
three parallel notification channels rather than one.

**Dependencies:** SQLite (on-device), Redis (server job queue),
WhatsApp Business API (primary channel for family notifications),
SMS via the configured primary OTP provider (§5.1 — secondary
channel for family notifications, used only for check-in/SOS, not
routine OTP traffic), Resend (email, HTO channel), WebSocket/
polling for dashboard updates.

**Failure modes:** Extended offline period → outbox processed in
timestamp order on reconnect; app killed by OS (aggressive battery
management on budget Android devices) → SQLite persists across
process death, a periodic background job (WorkManager on Android,
BGTaskScheduler on iOS) resumes sync independent of app process;
notification dispatch failure → retried 3x, then admin-queued —
the check-in/SOS record itself is never lost regardless of
notification outcome; **WhatsApp Business API outage or send
failure on a check-in or SOS notification → automatic SMS fallback
to the family contact's number within 60 seconds**, since family
notification on SOS is safety-critical and single-channel
dependency here is not acceptable the way it may be for lower-stakes
notifications; HTO-side notification (§5.8/US-19) is already
multi-channel (push + email + WhatsApp) and does not need this
change since email is already an independent fallback.

**Configuration note:** The WhatsApp-primary / SMS-secondary
channel order for family notifications is held as configuration
(`FAMILY_NOTIFY_CHANNEL_PRIMARY` / `FAMILY_NOTIFY_CHANNEL_SECONDARY`),
not hardcoded — consistent with the OTP, payment, and eSIM
patterns — so the order, or the 60-second failover window, can be
adjusted post-launch based on observed WhatsApp delivery
reliability in-region without a logic rewrite.

### 5.7 Package Balance & Usage Tracking
**Maps to:** US-17

**Voice:** Telnyx call-end webhook → duration → deduct from
`pstn_minutes_remaining`.

**Data:** Most eSIM aggregators do not provide real-time usage
webhooks — MVP uses a 15-min polling job against the aggregator's
usage endpoint per active profile. This is an honest limitation:
"remaining data" is near-real-time, not live.

**Dependencies:** Telnyx webhooks, eSIM aggregator usage API
(polling), Postgres, Redis (cache).

**Failure modes:** Polling failure → last known value shown with
"last updated X min ago"; balance race condition at exactly zero →
next call blocked at the voice call-control application level, no
negative balance allowed.

### 5.8 HTO Dashboard
**Maps to:** US-18, US-19, US-20

Next.js web application. Server-rendered pilgrim list sorted by
risk, polling every 60s for MVP (WebSocket upgrade deferred —
polling is simpler to ship correctly under the 7-month timeline
and sufficient at pilot volume).

**Dependencies:** Next.js (Cloudflare Workers), shared FastAPI/
Postgres/Redis backend.

**Failure modes:** Operator offline at the moment of an SOS →
email + WhatsApp channels are independent of dashboard session, so
at least one nearly always reaches them; large-manifest report
generation → background job with a ready notification if it would
exceed a reasonable request timeout.

### 5.9 Naira Pricing (Admin-Managed)
**Maps to:** US-26

Manual, admin-triggered price updates per tier — decouples package
pricing from a live FX API dependency and a daily automated job,
scaled down from an earlier fully-automated design (see US-26's
scope note in §4.10).

**Flow:** Admin opens the pricing screen on the dashboard, sees the
current Naira price per tier, edits a value, sees the % change
from the current price, confirms → new price takes effect
immediately for new checkouts → change logged (admin, timestamp,
old/new value) for audit.

**Dependencies:** None beyond the existing admin dashboard and
database — no external FX API, no scheduled job infrastructure.
Admin is expected to reference an external rate source (e.g. the
CBN/NFEM published rate) themselves when deciding on a new price;
DamDam doesn't fetch or display a live rate in-app for this
decision at this scope.

**Failure modes:** None specific to this flow beyond standard
admin-action error handling — there's no external dependency left
to fail. The tradeoff versus the original design: pricing only
updates when an admin actually acts, so a fast-moving FX event
between manual updates isn't caught automatically. Acceptable
given current Naira stability (see scope note); revisit if that
changes.

---

## 6. Timeline Note & Build Sequencing

Hajj 2027 falls on approximately May 14, 2027. HTOs need to be
onboarded and selling packages by February 2027 at the latest,
giving a real build runway of approximately 7 months from July
2026. Dual-platform (iOS + Android) scope, decided after the
original 7-month plan was sketched, adds real work — Apple
Developer Program enrollment, App Store review cycles (which can
take longer and are less predictable than Google Play review),
and TestFlight-based pilot distribution alongside the Play Store
internal testing track. This should be treated as added scope
against the existing timeline, not absorbed silently — see
infrastructure.md §11.4 for the CI/CD implications and §11.8 for
the added Apple Developer Program cost.

**Phased build sequencing** — this is the authoritative reference
for the "Phase 1," "Phase 3," "Phase 4" milestones already used in
`testing-qa.md` §14.6; those references predate this table's
existence in written form and are reconciled against it here.

| Phase | Timing | What ships |
|---|---|---|
| 0 — Vendor agreements | July 2026 | eSIM aggregator API access (Monty Mobile primary, eSIM Access secondary, 1Global tertiary), **voice vendor: Telnyx selected as the primary PSTN/VoIP provider for the Nigeria/Saudi Arabia corridors, following the quote comparison against Twilio — see `api-spec.md` §7.5's vendor-status flag and `infrastructure.md` for the rate rationale**, Paystack merchant account (Registered Business tier per `corporate-structure.md` §13.2), entity structuring started |
| 1 — Core checkout + eSIM + design foundation | Aug–Sep 2026 | Naira purchase flow, eSIM QR delivery, pre-departure guide — **plus the two prerequisites flagged in `testing-qa.md` §14.6: `design-system.md` produced via a dedicated design session, and the screenshot-generation CI step built** — both block any mobile screen PR merging, so they start immediately, not after the checkout flow is done |
| 2 — VoIP + CLI | Oct–Nov 2026 | In-app calling with verified Nigerian caller ID — this is the demo that wins HTO pilots |
| 3 — Safety layer + offline | Nov–Dec 2026 | SOS button, check-in, pre-departure emergency info (US-12, scoped down from full offline maps — see §4.4), HTO dashboard v1 — the offline-chaos test suite in `testing-qa.md` §14.4.1 must pass before this phase is considered done, not just before Phase 4 |
| 4 — HTO pilot onboarding | Jan–Feb 2027 | Live with 2–3 HTO partners, real users, fix what breaks — device matrix testing (`testing-qa.md` §14.3) and HTO usability testing (`testing-qa.md` §14.5) complete before this phase starts, per the milestones table |
| Hajj launch | May 2027 | First paying pilgrim cohort — load/chaos exercise and incident-response tabletop (`testing-qa.md` §14.4.2) complete beforehand |

**Note on a separate, differently-numbered roadmap:** the earlier
business/go-to-market strategic analysis (the McKinsey-style
document produced outside this `/docs` folder) also uses "Phase 0
through Phase 4" numbering, but for a *different* thing — HTO
channel rollout, State Board expansion, general-traveler
acquisition, and enterprise/government sales sequencing, not
engineering build sequencing. The two numbering schemes are not
the same phases and shouldn't be conflated; this table is the
engineering build sequence specifically, referenced by
`testing-qa.md` and nowhere else.

---

## 7. Payment Classification Note — App Store / Play Store Commission

DamDam's package purchases (eSIM data, PSTN calling minutes, and
all consumer/enterprise tiers) are **real-world telecom services**,
not digital content consumed inside the app — the same category
Uber, DoorDash, and airline booking apps fall into, which has
always been outside Apple's and Google's in-app purchase (IAP)
requirement, independent of the newer EU DMA / Epic v. Apple
external-payment-link provisions. This is not a workaround being
adopted — it's the standing classification this category of
purchase has always had, and it's why Airalo's own payment page
lists Visa/Mastercard/PayPal directly with no IAP involved.

**Practical consequence:** the Paystack web-view checkout already
specified in §5.3 and `api-spec.md` §7.3 should be built exactly as
speced, in-app, with **no Apple/Google commission owed** on package
purchases — not gated behind a special entitlement or region-
specific external-payment program.

**The actual risk is review misclassification, not the fee itself.**
A reviewer skimming quickly could mistake the purchase flow for
digital-goods unlocking, given the app also has account/PIN
features and a group safety layer. Mitigations, both cheap and
worth doing at submission time:

- Keep purchase-flow copy unambiguously framed as buying a
  telecom/connectivity service ("Buy Saudi Arabia data & calling"),
  never "unlock" or "credits" language that reads as digital-goods
  framing
- Include a short explanatory note in App Store Connect's review
  notes at submission, citing the eSIM/telecom nature of the
  purchase, to head off a reviewer's first-instinct question
- If any future roadmap item introduces genuine in-app-only digital
  content (not currently planned anywhere in this spec suite), that
  specific item — and only that item — would need IAP even while
  packages stay on Paystack

---

## 8. Corporate Structure — Summary Reference

The full corporate entity structure (UAE parent, Nigeria OpCo,
payment rail allocation) is documented separately in
[`corporate-structure.md`](./corporate-structure.md), since it's a
legal/business decision referenced by multiple specs
(`security.md` §10.1, `scaling-infrastructure.md` §12.6) rather
than a product requirement in its own right. Read that document for
the reasoning; the short version: a single UAE entity holds the
brand/IP for now, a wholly-owned Nigerian subsidiary handles local
KYC and the Paystack relationship, and multi-entity treasury
structures are deliberately deferred until revenue justifies the
added complexity.

Hajj 2027 falls on approximately May 14, 2027. HTOs need to be
onboarded and selling packages by February 2027 at the latest,
giving a real build runway of approximately 7 months from July
2026. Dual-platform (iOS + Android) scope, decided after the
original 7-month plan was sketched, adds real work — Apple
Developer Program enrollment, App Store review cycles (which can
take longer and are less predictable than Google Play review),
and TestFlight-based pilot distribution alongside the Play Store
internal testing track. This should be treated as added scope
against the existing timeline, not absorbed silently — see
infrastructure.md §11.4 for the CI/CD implications and §11.8 for
the added Apple Developer Program cost.

---

## 9. Amendment — English/French Product Support

NG8’s “English only for MVP” statement is superseded. DamDam now supports
explicit English/French selection across mobile, dashboard, API responses, and
transactional/safety notifications. Locale is a recipient preference and must
not be inferred from country where a market is multilingual.

This does not greenlight a new country by itself. Nigerian phone, NAHCON,
NGN/payment, identity, and market-specific legal assumptions remain separate
expansion work. French production launch is gated by the native, safety, legal,
vendor-template, and screenshot reviews in `localization.md`.

---

## 10. Amendment — Product Reset to Global Consumer and Enterprise Connectivity

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**

This amendment resets the product at the user's explicit request. Sections 1–9
above are **not deleted** — they remain the record of the Hajj-pilgrim product
and the decisions taken for it. Where §§1–9 and this section disagree, this
section governs. The reference for which legacy concept is retired, generalized,
deferred or purely historical is
[`implementation/SCOPE-DISPOSITION.md`](./implementation/SCOPE-DISPOSITION.md).

The full plan is [`implementation/IMPLEMENTATION-PLAN.md`](./implementation/IMPLEMENTATION-PLAN.md);
the build sequence is [`implementation/README.md`](./implementation/README.md).

### 10.1 Reset product definition

DamDam is a global eSIM and carrier-voice platform for individual consumers and
for enterprise and government organizations. A customer buys connectivity in
DamDam, installs an eSIM, and uses their phone's **normal dialer and mobile
data** — one carrier-enabled profile carries both. Global reach is the expansion
objective; each released market, device, number type and roaming capability must
be explicitly supported before it is sold.

**In scope for the first production release:** consumer mobile app (Home, Plans,
My Line, Account), enterprise/government dashboard, and a separate internal
operations surface.

**Removed:** family contacts, offline SOS, arrival geofencing, and the
Hajj/pilgrim/NAHCON framing including mandatory departure dates and a fixed
Saudi destination. Removing DamDam's SOS says nothing about carrier
emergency-calling obligations on a real cellular line — that is a separate
supplier and legal question under D1.

**Removed as a proposed default, pending confirmation:** the remaining check-in
and welfare workflow. It must not be quietly retained as enterprise tracking.

**Deferred:** external verified caller ID, +234 retention and porting,
app/browser VoIP, additional carrier integrations, SSO/SCIM, MDM deployment,
reseller marketplace, PBX/SIP, referral rewards, AI call assistance and
multi-region deployment. Recurring subscriptions may be promoted into scope
after the D5 pricing decision; the data model should be able to support them
without shipping them.

### 10.2 User types replacing §3

| §3 type | Disposition |
|---|---|
| Pilgrim | Replaced by **Consumer** — any individual buying connectivity for themselves. No pilgrimage, departure date or destination requirement. |
| HTO Operator | Replaced by **Organization member**, with owner, administrator, billing and member roles. Government is an organization category, not a separate type. |
| Family Contact | **Removed.** |
| System Administrator | Replaced by **Internal operator**, on a distinct privileged surface. Enterprise administrators never inherit cross-customer internal access. |

Launch claims no universal government certification or data-residency
compliance; additional procurement and security requirements are evaluated per
contract.

### 10.3 Revised user journeys

**Consumer purchase:** browse plans → check device and destination eligibility →
sign up → immutable quote → pay → order provisioned → install eSIM → select the
native line for voice and data → use → top up. Secure installation guidance and
a timestamped last-known usage reading remain available offline. Ordinary
carrier calling requires no background location, no contacts access and no
microphone permission.

**Consumer recovery:** a returning user restores their account and service
records without family, SOS or verified-CLI dependencies. Restoring an account
does not move an installed eSIM. A new device follows the supplier-supported
reinstallation, transfer or replacement procedure; if unsupported, show the
limitation and a support/refund route under the agreed policy before promising
service recovery on that device.

**Enterprise:** create an organization → invite administrators (MFA required) →
import people with row-level validation → bulk quote → fund a prepaid balance →
order → assign to recipients → the employee installs and consents → reconciled
spend and departmental exports → offboarding revokes work access and future
spending while respecting personal services and carrier ownership rules.

**Internal operations:** exception queue → supplier reconciliation → refund,
dispute or audited adjustment → recorded outcome.

Two boundaries hold everywhere: dashboard provisioning never installs an eSIM
silently on an unmanaged phone, and a personal/work payer selection in the app
never overrides which native SIM line the handset uses for a call. Organization
credit is not automatically a shared carrier data pool.

### 10.4 Disposition of US-01 – US-26

These IDs are **retained as historical references** and are never reused for an
unrelated requirement.

| Legacy story | Disposition | Successor |
|---|---|---|
| US-01 Nigerian-phone signup | Replaced — identity is global and, as a proposed default, email-based | US-29 |
| US-02 4-digit PIN | Replaced — device-appropriate app lock, defined with the identity model | US-29 |
| US-03 Family contact nomination | **Retired** | — |
| US-04 HTO business account | Replaced — organization creation and approval | US-29, US-39 |
| US-05 CSV manifest upload | Replaced — validated people import | US-39 |
| US-06 Bulk package purchase | Replaced — bulk quote and order with partial-failure recovery | US-40 |
| US-07 WhatsApp redemption message | Replaced — invitation and redemption bound to the intended recipient | US-37, US-40 |
| US-08 Browse packages | Replaced — supported-market catalog with eligibility | US-31, US-37 |
| US-09 Naira card payment | Replaced — multi-currency routing; Paystack retained conditionally for approved local NGN | US-33 |
| US-10 Device eSIM compatibility | Replaced — device eligibility checked before payment | US-31, US-37 |
| US-11 eSIM download | Replaced — carrier profile, line and installation lifecycle | US-35, US-38 |
| US-12 Emergency contacts content | **Retired** (already reduced by §6.20) | — |
| US-13 Arrival activation prompt | **Retired** — geofencing removed | — |
| US-14 Verified caller ID call | **Deferred** — outbound identity is the carrier-assigned number | US-35 |
| US-15 Offline check-in | **Proposed retirement**, subject to the product-default record in `implementation/DECISIONS.md` | US-30 for any transition |
| US-16 SOS trigger | **Retired** | — |
| US-17 Remaining data and minutes | Replaced — real supplier usage reconciliation with freshness | US-36, US-38 |
| US-18 HTO check-in roster | **Proposed retirement** with the remaining welfare workflow | US-30 for any transition |
| US-19 HTO SOS alerts | **Retired** | — |
| US-20 HTO report download | Replaced — departmental spend and usage exports | US-40 |
| US-21 Family WhatsApp check-in | **Retired** | — |
| US-22 Family WhatsApp SOS | **Retired** | — |
| US-23 Session persistence | Retained in substance; re-specified with the global identity model | US-29 |
| US-24 Offline safety queue | Retire SOS paths safely; check-in paths follow the product-default decision. Preserve applicable tests and account isolation throughout | US-30 |
| US-25 Duplicate-purchase prevention | Retained and strengthened — durable operation reference and reconciliation | US-32 |
| US-26 Manual Naira pricing | Replaced — multi-currency tariff versions and immutable quotes | US-31 |

### 10.5 New stories US-27 – US-43

`US-27` onward were free on the base commit `6790c74`; no existing ID was
overwritten. Chunk-to-story routing is in
[`implementation/STORY-MAP.md`](./implementation/STORY-MAP.md). Chunk files hold
each chunk's own detailed criteria; the criteria below are what must hold across
a story's chunks.

**US-27** [P0] — As the product owner, I want the repository specifications to
describe the reset product and the current working rules, so that every later
chunk builds against one coherent scope.
- AC-27.1: `AGENTS.md` states Claude implements and Codex independently reviews
  and may refactor, with no conflicting per-area ownership table
- AC-27.2: The develop/CI baseline is refreshed and recorded with an actual base
  SHA, available deployment evidence, and the differences from the historical
  6790c74 review — with no failure described as fixed
- AC-27.3: The build pack, including the implementation plan, is present in
  `docs/implementation/`
- AC-27.4: Every one of the 30 chunks maps to a registered story, and every
  legacy Hajj/family/SOS/WebRTC/verified-CLI/HTO reference in the active specs
  is classified retired, generalized, deferred or historical
- AC-27.5: D1–D6 are recorded OPEN with owner, required evidence and affected
  chunks; proposed defaults are labelled as proposed, not as approvals
- AC-27.6: Module ownership, the revised journeys and the revised screen/locale
  matrix scope are defined; the docs index and release criteria are coherent
- AC-27.7: Documentation links resolve and existing documentation checks pass

**US-28** [P0] — As an engineer, I want core domain models and migration
boundaries, so that money, orders, connectivity and tenancy have one contract.
- AC-28.1: Seller, payer, service recipient, currency and settlement are
  separate fields, not conflated
- AC-28.2: Every money value carries an explicit ISO currency and a correctly
  scaled amount; cross-currency addition is impossible by construction
- AC-28.3: Migrations are additive first; upgrade from the existing schema
  preserves historical receipts, balances, orders and audit history
- AC-28.4: Each change is a numbered `data-model.md` amendment with the
  `api-spec.md` contract kept in sync

**US-29** [P0] — As a customer, I want a global account with reliable recovery,
and as an organization I want isolated memberships, so that access is correct.
- AC-29.1: Account identity and recovery are independent of any carrier-assigned
  number
- AC-29.2: Recovery works without family, SOS or verified-CLI dependencies
- AC-29.3: Organization membership, roles and invitations are enforced in APIs,
  background jobs, exports and storage access — not only in the UI
- AC-29.4: A negative cross-tenant request fails at the object level, proven by
  test, for every organization-scoped resource
- AC-29.5: Administrator MFA is required; session and token revocation take
  effect immediately

**US-30** [P0] — As the product owner, I want family, safety and app-calling
features retired safely, so that removal loses no history and orphans no work.
- AC-30.1: New enrollment and dispatch stop before any data is deleted
- AC-30.2: Queued work and old clients cannot revive a removed notification path
- AC-30.3: Order, payment and audit history survives removal intact
- AC-30.4: **Original finding 1** — user A queues an offline event and signs
  out; user B signs in; no A event is dispatched or attributed as B, across app
  restart and across a delayed callback arriving after the switch. Legacy rows
  without trustworthy ownership are quarantined, never rebound
- AC-30.5: Release builds request no contacts, background-location or app-call
  permission that the product no longer uses
- AC-30.6: Sensitive legacy records are deleted per the approved retention
  policy; schema is dropped only after compatibility requirements end

**US-31** [P0] — As a customer, I want to see only what I can actually buy and
use, so that a purchase cannot promise unsupported service.
- AC-31.1: Selling market, visited country, calling destination and device
  support are four distinct concepts in the catalog
- AC-31.2: A quote is immutable, priced against a named tariff version, and
  expires
- AC-31.3: An unsupported device or destination is refused **before** payment,
  with useful guidance
- AC-31.4: No public offer exists for a market not confirmed under D1/D2; a
  test-only catalog is clearly marked as such

**US-32** [P0] — As the business, I want orders and the ledger to be exactly
correct under concurrency and failure, so that nobody is double-charged or
double-provisioned.
- AC-32.1: Ledger entries are immutable, balanced and currency-specific;
  funding, reservation, consumption, release and compensating adjustment are
  distinct entry types
- AC-32.2: Concurrent purchases against one balance cannot oversell, proven on
  PostgreSQL
- AC-32.3: Repeated and reordered webhooks cannot double-credit or
  double-provision
- AC-32.4: **Original finding 4** — the operation reference and supplier attempt
  are persisted before dispatch
- AC-32.5: Accepted, definitively-rejected and outcome-unknown are classified
  separately; an unknown outcome reconciles against the original supplier and
  never fails over to another
- AC-32.6: An accepted-but-response-lost attempt does not purchase a second
  profile, including after a worker restart mid-flight

**US-33** [P0] — As a customer, I want payment to work in my currency through an
approved processor, so that checkout is trustworthy.
- AC-33.1: Payment routing is a boundary; no processor-specific shape leaks into
  the API contract
- AC-33.2: Raw card details are never collected by the DamDam backend; checkout
  is hosted or tokenized
- AC-33.3: Paystack is retained only for approved eligible local NGN business
  through a matching merchant entity
- AC-33.4: Wallet checkout means Apple Pay/Google Pay through the processor
  where supported
- AC-33.5: Currency mismatch fails loudly; webhook authenticity is verified
- AC-33.6: Live mode remains blocked until D3 and D4 are recorded; sandbox
  evidence closes software work only

**US-34** [P0] — As the business, I want refunds, disputes and settlement to
reconcile, so that the books close.
- AC-34.1: A refund maps to the correct original charge by its original
  reference
- AC-34.2: Tax, FX and fees reconcile against processor settlement records
- AC-34.3: Receipts state the selling legal entity as data, never hardcoded
- AC-34.4: A dispute has a recorded lifecycle and does not corrupt the ledger

**US-35** [P0] — As a customer, I want a real carrier line with data and native
voice, so that the product does what it claims.
- AC-35.1: eSIM profile, carrier line, assigned number, service entitlement and
  activation request are separate resources
- AC-35.2: Provisioning is idempotent and supports lookup by the original
  operation reference
- AC-35.3: The assigned number is the outbound identity; no third-party verified
  CLI is claimed, and no +234 retention or porting is promised
- AC-35.4: Number, line and suspension lifecycles are complete, including
  supplier-supported suspension distinguished from a merely requested one
- AC-35.5: Physical proof — on approved iOS and Android devices, install the
  eSIM, use data, and place a native-dialer call to Nigeria with DamDam closed;
  capture visited network, device/OS, supplier reference and rate version.
  **No simulator-only or WebRTC evidence closes this criterion**

**US-36** [P0] — As a customer, I want my balance to reflect what I actually
used, so that spending controls mean something.
- AC-36.1: **Original finding 3** — real supplier usage ingestion reduces the
  displayed allowance, with persistent cursors, retry and deduplication by
  supplier event ID
- AC-36.2: Delayed, reordered and corrected readings reconcile without double
  debit; provisional usage is distinguished from finalized billing
- AC-36.3: A stale reading is visibly stale, with its timestamp
- AC-36.4: Caps and suspension are enforced supplier-side where the promised
  contract requires it; an app-side balance derived from delayed records is
  never presented as a guaranteed hard cap
- AC-36.5: Tariff versions are recorded per charge

**US-37** [P0] — As a new customer, I want one continuous journey from opening
the app to using my line, so that nothing dead-ends.
- AC-37.1: Home, Plans, My Line and Account are complete and reachable
- AC-37.2: **Original finding 2** — signup → purchase *or* invitation/code
  redemption → provisioning → installation → Home/My Line runs end to end
  through production navigation
- AC-37.3: An activation link works from both cold and warm launch; expired and
  already-used codes, and back navigation, all behave correctly
- AC-37.4: Redemption binds to the intended recipient
- AC-37.5: Paid-but-pending, payment failure and installation failure each have
  a tested route out
- AC-37.6: English and French are complete for every new surface

**US-38** [P0] — As a customer, I want My Line, installation, receipts, support
and deletion to work, so that I can run my own account.
- AC-38.1: Installation guidance is real for the supported launch device matrix,
  with a QR fallback; no placeholder guides ship
- AC-38.2: Native line selection guidance is correct for dual-SIM handsets
- AC-38.3: Secure installation details and the last-known usage reading remain
  available offline
- AC-38.4: Receipts, support contact and account deletion work without any
  family, SOS or verified-CLI dependency
- AC-38.5: A returning user recovers their account and service records. On a new
  device, offer only supported profile reinstallation/transfer/replacement;
  otherwise explain the limitation and the agreed support/refund path. Test both
  supported and unsupported recovery without reusing one-time activation codes

**US-39** [P0] — As an organization administrator, I want people, teams and
imports, so that I can manage who gets connectivity.
- AC-39.1: A person record is distinct from a member role
- AC-39.2: CSV import validates row by row and reports per-row outcomes
- AC-39.3: Teams, departments and cost centers are assignable and exportable
- AC-39.4: Every list, export and background job is tenant-scoped

**US-40** [P0] — As an organization, I want bulk provisioning, funding and
offboarding, so that a real deployment is manageable.
- AC-40.1: 50 recipients import, quote, fund, order and assign without duplicate
  charges
- AC-40.2: Partial bulk failure is recoverable per line, with visible per-line
  progress
- AC-40.3: An allocation is bound to its recipient; the employee installs and
  consents
- AC-40.4: Approved budgets and top-ups are enforced; a requested restriction is
  visibly distinct from a confirmed carrier restriction
- AC-40.5: Offboarding revokes work access and future spending while respecting
  personal services and carrier ownership/reassignment rules
- AC-40.6: A restricted administrator cannot cross a role or tenant boundary

**US-41** [P0] — As an internal operator, I want exception queues and audited
adjustments, so that support can resolve real failures.
- AC-41.1: Internal operations are a distinct privileged surface; enterprise
  administrators never inherit cross-customer access
- AC-41.2: Supplier exception, payment reconciliation and refund queues are
  actionable
- AC-41.3: Every adjustment is audited with actor, reason and before/after state
- AC-41.4: Exports redact secrets and activation material

**US-42** [P0] — As the release owner, I want a trustworthy CI and production
baseline, so that a green pipeline means something.
- AC-42.1: **Original finding 5a** —
  `tests/test_auth_api.py::test_otp_request_and_verify_contract` passes under
  one controlled test clock shared by token creation and JWT validation, with
  both valid and expired cases, and **without** disabling production expiry
  checks
- AC-42.2: **Original finding 5b** — strengthen the existing exact-count check
  (32 images on the baseline) so the screenshot job asserts a complete,
  nonempty manifest for the revised screen/locale matrix and fails when an
  expected image is missing, so intermittency surfaces as a failure. The
  historical 0/32 and the 32 images observed on 2026-09-08 both describe the old
  matrix and neither carries forward
- AC-42.3: Staging and production are isolated, with least-privilege
  credentials, verified webhooks, tested backups and restoration, monitoring and
  alerting
- AC-42.4: iOS and Android builds are signed, with store privacy and payment
  disclosures matching the actual product
- AC-42.5: The release signoff validator and its scenario matrix match the reset
  scope; no removed feature is still demanded as release evidence
- AC-42.6: No production mock supplier mode can be enabled in a release build

**US-43** [P0] — As the release owner, I want integrated, physical and pilot
evidence, so that launch is a decision and not a hope.
- AC-43.1: The integrated matrix passes: purchase, provisioning, installation,
  usage, top-up, refund, enterprise bulk and offboarding
- AC-43.2: Migration from the existing production schema is proven on
  representative data
- AC-43.3: Failure recovery is proven for supplier timeout, worker crash, double
  webhook, partial bulk order and stale usage
- AC-43.4: Physical device evidence exists per AC-35.5 on both platforms
- AC-43.5: A real enterprise pilot administrator completes the flow, and
  material issues found are fixed
- AC-43.6: Every launch checklist item in
  `implementation/IMPLEMENTATION-PLAN.md` §10 has evidence against the release
  commit
- AC-43.7: D1–D6 are recorded as resolved with evidence, or the affected scope
  is explicitly not launched

### 10.6 What this amendment does not do

It changes no application code, no migration and no CI configuration. It does
not claim any defect is fixed: the current, observed and historical failures are
recorded in [`implementation/BASELINE.md`](./implementation/BASELINE.md). It does
not close any external decision — D1–D6 are all open in
[`implementation/DECISIONS.md`](./implementation/DECISIONS.md), and the proposed
defaults recorded there (welfare removal, email-based recovery, a new assigned
number, prepaid charging) are proposals awaiting the founder, not approvals.
