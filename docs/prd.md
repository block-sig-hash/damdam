# Product Requirements Document
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
- AC-08.6: Prices calculated daily from the USD reference price
  at the cached NFEM rate

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

**US-12** [P1] — As a Pilgrim, I want to cache offline maps of the
Haram, Mina, and Arafat before departure so that I can navigate
with zero connectivity.
- AC-12.1: "Download before you travel" screen, clearly labelled
- AC-12.2: Covers Masjid al-Haram, Mina, Arafat, Madinah
- AC-12.3: Includes emergency contacts, key Arabic phrases,
  package details
- AC-12.4: Pack ≤ 50MB
- AC-12.5: Progress bar shown
- AC-12.6: Fully functional offline once downloaded
- AC-12.7: Shows "downloaded on [date]"

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
- AC-14.1: CLI verification (OTP) completed once at account setup
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

**US-26** [P1] — As the System, I want to update Naira prices
daily using the NFEM rate without manual intervention.
- AC-26.1: Daily 09:00 WAT scheduled job fetches current rate
- AC-26.2: Prices recalculated and cached
- AC-26.3: Client always reads from the daily cache
- AC-26.4: Fetch failure → previous rate retained, admin alerted
- AC-26.5: >5% day-over-day change → held for admin review before
  going live

---

## 5. Feature Specifications

Each module maps to the user stories above. Format: Description →
Trigger → Flow → Dependencies → Failure modes.

### 5.1 Authentication & Identity
**Maps to:** US-01, US-02, US-04, US-23

Phone-number-based identity for pilgrims (OTP + PIN); email-based
for HTO operators (email + password + admin approval gate).

**Flow — Pilgrim:** Phone entry → Twilio Verify OTP (Redis-cached,
10-min TTL) → JWT issued on success → PIN set (bcrypt hash, never
transmitted post-set).

**Flow — HTO Operator:** Email + password registration → email
verification link (24h expiry) → `pending_approval` state → manual
admin review of NAHCON licence → approved, notified via email +
WhatsApp.

**Dependencies:** Twilio Verify, Redis, Postgres, Resend.

**Failure modes:** OTP delivery failure → 30s cooldown, max 3
resends/hour; Twilio outage → no fallback for Path A phone
verification (hard dependency); PIN lockout → 30-min lock, OTP
recovery available immediately.

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
  none exists) against a known-supported-models list to decide
  whether to show the compatibility warning or the manual guide.

**Flow:**
1. Compatibility check (platform-specific, as above); result
   logged to `device_compatibility_log`
2. Unsupported → warning modal (AC-10.3), QR-only path
3. Aggregator (eSIM Access as primary; Monty Mobile as a qualified
   secondary for redundancy — see `data-model.md` §6.6 for why a
   second supplier is a deliberate risk decision, not just cost
   comparison) issues an eSIM profile: `iccid`, `activation_code`
   (LPA string), QR image URL
4. Activation trigger: **primary** is the date-based banner (7
   days pre-departure, no permission required); **secondary** is
   the opt-in geofence push
5. Android carrier-privilege devices: in-app one-tap switch.
   **All other devices (all iOS, non-privileged Android):**
   device-model-specific manual guide with screenshots

**Dependencies:** eSIM Access (primary aggregator), Monty Mobile
(secondary aggregator, onboarded and tested before relied upon in
production — not dynamically selected per-request at MVP), Airalo
Partner API (evaluated, not the committed primary — see
`data-model.md` §6.6), Android `EuiccManager`, Firebase Cloud
Messaging (push, cross-platform via React Native Firebase), Android
Geofencing API / iOS Core Location region monitoring.

**Failure modes:** Aggregator issuance failure → retried with
backoff, admin-queued after 3 attempts; device-specific download
failure → QR always available as universal fallback; geofence
non-fire → date-based banner is the reliable primary path on both
platforms.

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
PSTN-terminated calls.

**Flow:** Twilio Verify OTP to the pilgrim's registered number
(reuses login number, no separate entry) → `verified_cli` flag set
→ calling via Twilio Voice SDK (React Native, cross-platform) →
backend TwiML sets `callerId` to the verified number for PSTN legs
→ DamDam-to-DamDam calls route Client-to-Client, bypassing PSTN
entirely (free) → call events via Twilio webhooks drive balance
deduction (5.7).

**Dependencies:** Twilio Verify, Twilio Voice (WebRTC + PSTN
termination), Twilio TwiML application.

**Failure modes:** Token expiry mid-session → SDK auto-refreshes
5 min before expiry; connectivity drop mid-call → graceful
termination, billed only for connected seconds; Twilio outage →
calling degrades with an in-app banner while check-in/SOS continue
functioning independently.

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
WhatsApp Business API, Resend, WebSocket/polling for dashboard
updates.

**Failure modes:** Extended offline period → outbox processed in
timestamp order on reconnect; app killed by OS (aggressive battery
management on budget Android devices) → SQLite persists across
process death, a periodic background job (WorkManager on Android,
BGTaskScheduler on iOS) resumes sync independent of app process;
notification dispatch failure → retried 3x, then admin-queued —
the check-in/SOS record itself is never lost regardless of
notification outcome.

### 5.7 Package Balance & Usage Tracking
**Maps to:** US-17

**Voice:** Twilio call-end webhook → duration → deduct from
`pstn_minutes_remaining`.

**Data:** Most eSIM aggregators do not provide real-time usage
webhooks — MVP uses a 15-min polling job against the aggregator's
usage endpoint per active profile. This is an honest limitation:
"remaining data" is near-real-time, not live.

**Dependencies:** Twilio webhooks, eSIM aggregator usage API
(polling), Postgres, Redis (cache).

**Failure modes:** Polling failure → last known value shown with
"last updated X min ago"; balance race condition at exactly zero →
next call blocked at the TwiML application level, no negative
balance allowed.

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

### 5.9 Dynamic Naira Pricing
**Maps to:** US-26

Daily FX-indexed price calculation, decoupling package pricing
from manual updates.

**Flow:** 09:00 WAT cron fetches USD/NGN from a currency data API
→ computes Naira price per tier from the canonical USD reference
→ 5% day-over-day guardrail (holds + alerts admin if exceeded) →
writes to `daily_price_cache`.

**Dependencies:** A currency/FX data API (candidates:
exchangerate-api.com, currencyapi.com — neither is an official
NFEM source; the pricing model already treats NFEM as a baseline
approximation, not a promise of exact parity).

**Failure modes:** API unreachable → previous cached rate
persists, admin alerted; outlier rate → guardrail prevents it
reaching users automatically.

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
| 0 — Vendor agreements | July 2026 | eSIM aggregator API access (Airalo/eSIM Access), **voice vendor decision: quote both Twilio and Telnyx for the Nigeria/Saudi Arabia corridors specifically, decide based on real PSTN termination rates — see `api-spec.md` §7.5's vendor-status flag — since this is the single largest variable cost lever in the margin model**, Paystack merchant account (Registered Business tier per `corporate-structure.md` §13.2), entity structuring started |
| 1 — Core checkout + eSIM + design foundation | Aug–Sep 2026 | Naira purchase flow, eSIM QR delivery, pre-departure guide — **plus the two prerequisites flagged in `testing-qa.md` §14.6: `design-system.md` produced via a dedicated design session, and the screenshot-generation CI step built** — both block any mobile screen PR merging, so they start immediately, not after the checkout flow is done |
| 2 — VoIP + CLI | Oct–Nov 2026 | In-app calling with verified Nigerian caller ID — this is the demo that wins HTO pilots |
| 3 — Safety layer + offline | Nov–Dec 2026 | SOS button, check-in, offline maps, HTO dashboard v1 — the offline-chaos test suite in `testing-qa.md` §14.4.1 must pass before this phase is considered done, not just before Phase 4 |
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
