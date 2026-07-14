#!/usr/bin/env bash
# create-issues.sh — Bulk-create GitHub Issues for all DamDam PRD user stories
#
# Usage:
#   cd ~/damdam
#   chmod +x create-issues.sh
#   ./create-issues.sh
#
# Requires: gh CLI already authenticated (Phase 2.2), run from inside the
# damdam repo (or anywhere — gh will target the repo via --repo if you add it).
#
# Safe to re-run: gh issue create does NOT dedupe automatically, so if you
# run this twice you'll get 26 duplicate issues. If you need to re-run after
# a partial failure, comment out the blocks for stories already created.

set -e

REPO="block-sig-hash/damdam"   # change if your repo path differs

create_issue() {
  local title="$1"
  local body="$2"
  local labels="$3"
  echo "Creating: $title"
  gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels"
}

# ---------------------------------------------------------------------------
# US-01
create_issue \
"US-01 [P0]: Pilgrim phone-number signup (OTP)" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** download the app and sign up using my Nigerian phone number **so that** I can create an account without needing an invitation.

Reference: docs/prd.md §4.1

### Acceptance Criteria
- [ ] AC-01.1: App accepts only valid Nigerian phone numbers (070x, 080x, 081x, 090x, 091x, 11 digits)
- [ ] AC-01.2: App rejects international numbers at entry
- [ ] AC-01.3: App sends a 6-digit OTP via SMS within 10 seconds
- [ ] AC-01.4: OTP expires after 10 minutes
- [ ] AC-01.5: 3 OTP attempts allowed before a 60-second lockout
- [ ] AC-01.6: On successful OTP entry, account is created and user is logged in
- [ ] AC-01.7: If the number already has an account, direct to login
- [ ] AC-01.8: If the primary OTP provider (Termii) has not returned a delivery confirmation within 180 seconds (config value: OTP_FAILOVER_THRESHOLD_SECONDS), the system automatically retries via the secondary OTP provider (Twilio Verify) without user action or visible error
- [ ] AC-01.9: UI shows a "Sending your code..." state after 10 seconds and offers a manual resend option from 30 seconds, independent of the automatic provider failover threshold

Note: OTP provider decision — Termii (primary, direct-carrier + lower cost for Nigerian numbers), Twilio Verify (secondary, triggered at 180s to avoid false failovers on delayed delivery receipts). Threshold and provider order are config values, adjustable post-launch without a logic change. Per docs/prd.md §5.1 (updated).
EOF
)" \
"priority-P0,type-feature,area-auth"

# ---------------------------------------------------------------------------
# US-02
create_issue \
"US-02 [P0]: PIN setup after phone verification" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** set a 4-digit PIN after phone verification **so that** my account is protected without needing a password I might forget.

Reference: docs/prd.md §4.1

### Acceptance Criteria
- [ ] AC-02.1: PIN must be 4 digits, not sequential or repeated
- [ ] AC-02.2: PIN entry is masked, entered twice to confirm
- [ ] AC-02.3: PIN unlocks the app on subsequent opens
- [ ] AC-02.4: 5 failed attempts → 30-minute lock, OTP-based recovery available immediately
EOF
)" \
"priority-P0,type-feature,area-auth"

# ---------------------------------------------------------------------------
# US-03
create_issue \
"US-03 [P0]: Nominate family contact via WhatsApp" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** nominate a family contact's WhatsApp number during setup **so that** they receive my check-ins and SOS alerts without needing to install the app.

Reference: docs/prd.md §4.1

### Acceptance Criteria
- [ ] AC-03.1: Pilgrim enters a Nigerian phone number for the family contact
- [ ] AC-03.2: System sends a WhatsApp notification to the nominated number; no confirmation required from them
- [ ] AC-03.3: Pilgrim can update the nominated number at any time
- [ ] AC-03.4: One family contact per pilgrim for MVP
EOF
)" \
"priority-P0,type-feature,area-onboarding"

# ---------------------------------------------------------------------------
# US-04
create_issue \
"US-04 [P0]: HTO Operator business account registration" \
"$(cat <<'EOF'
**As an** HTO Operator, **I want to** create a business account on the web dashboard **so that** I can manage packages for my pilgrims.

Reference: docs/prd.md §4.2

### Acceptance Criteria
- [ ] AC-04.1: Registration requires business name, operator name, email, phone number, NAHCON licence number
- [ ] AC-04.2: Licence number recorded but manually reviewed (not programmatically validated) for MVP
- [ ] AC-04.3: Email verification required before account activation
- [ ] AC-04.4: New accounts pending admin approval (target: 24 hours)
- [ ] AC-04.5: Operator notified via email + WhatsApp on approval
EOF
)" \
"priority-P0,type-feature,area-dashboard"

# ---------------------------------------------------------------------------
# US-05
create_issue \
"US-05 [P0]: HTO CSV manifest upload" \
"$(cat <<'EOF'
**As an** HTO Operator, **I want to** upload a CSV manifest of my pilgrims **so that** I can provision packages for them in bulk.

Reference: docs/prd.md §4.2

### Acceptance Criteria
- [ ] AC-05.1: CSV only, max 500 rows per upload
- [ ] AC-05.2: Required columns: first_name, last_name, phone_number
- [ ] AC-05.3: Optional: passport_number, seat_number
- [ ] AC-05.4: Every phone number validated (Nigerian format) before acceptance
- [ ] AC-05.5: Invalid rows flagged with row number + reason; valid rows accepted independently (no all-or-nothing)
- [ ] AC-05.6: Operator sees a preview before confirming
- [ ] AC-05.7: Duplicate phone numbers flagged as warnings, not errors
EOF
)" \
"priority-P0,type-feature,area-dashboard"

# ---------------------------------------------------------------------------
# US-06
create_issue \
"US-06 [P0]: HTO bulk package purchase (incl. Family-tier grouping)" \
"$(cat <<'EOF'
**As an** HTO Operator, **I want to** select pilgrims from my manifest and purchase a package tier for them at the wholesale rate — including forming Family-tier groups — **so that** I can resell DamDam as part of my Hajj package.

Reference: docs/prd.md §4.2, data-model.md §6.5

### Acceptance Criteria
- [ ] AC-06.1: Operator selects a subset of unordered pilgrims from the manifest (individuals for a bulk tier, or a pre-grouped Family set)
- [ ] AC-06.2: Dashboard shows per-pilgrim wholesale price, total, and estimated retail margin
- [ ] AC-06.3: Payment is via invoice (bank transfer) for MVP
- [ ] AC-06.4: PDF invoice generated and emailed on order confirmation
- [ ] AC-06.5: Packages provisioned and activation links sent only after DamDam admin manually confirms payment received
- [ ] AC-06.6: A manifest may have multiple orders across different tiers/groupings; remaining unordered pilgrims stay available for a subsequent order
EOF
)" \
"priority-P0,type-feature,area-dashboard,area-payments"

# ---------------------------------------------------------------------------
# US-07
create_issue \
"US-07 [P1]: Pilgrim activation via HTO-issued WhatsApp link" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** receive a WhatsApp message with an activation link from my HTO **so that** I can activate my pre-purchased package without paying myself.

Reference: docs/prd.md §4.2

### Acceptance Criteria
- [ ] AC-07.1: Message sent within 5 minutes of payment confirmation
- [ ] AC-07.2: Includes operator name, tier, deep link (Play Store / App Store fallback if app not installed), unique 8-character activation code
- [ ] AC-07.3: Code is single-use, expires after 30 days
- [ ] AC-07.4: New pilgrim: OTP → PIN → package auto-attached via code
- [ ] AC-07.5: Existing pilgrim: log in, package attached via code
- [ ] AC-07.6: Post-activation experience identical to Path A
EOF
)" \
"priority-P1,type-feature,area-onboarding"

# ---------------------------------------------------------------------------
# US-08
create_issue \
"US-08 [P0]: Browse available packages" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** browse available packages with clear descriptions **so that** I can choose the right one.

Reference: docs/prd.md §4.3

### Acceptance Criteria
- [ ] AC-08.1: All four tiers shown: Starter, Basic, Standard, Family
- [ ] AC-08.2: Each shows name, NGN price, data GB, PSTN minutes, 3 feature bullets
- [ ] AC-08.3: "Recommended" badge on Standard
- [ ] AC-08.4: Family tier shows a group-size selector (2–8) with the total price recalculating live as size changes
- [ ] AC-08.5: "What's included" expandable section
- [ ] AC-08.6: Prices calculated daily from the USD reference price at the cached NFEM rate
EOF
)" \
"priority-P0,type-feature,area-payments"

# ---------------------------------------------------------------------------
# US-09
create_issue \
"US-09 [P0]: Naira payment (card, bank transfer, USSD)" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** pay in Naira via card, bank transfer, or USSD **so that** I do not need a foreign currency card.

Reference: docs/prd.md §4.3, §5.3, data-model.md §6.7

### Acceptance Criteria
- [ ] AC-09.1: Payment web view opens in-app on "Buy now" — Paystack by default, Flutterwave if Paystack checkout initialization fails; the pilgrim never sees a processor choice
- [ ] AC-09.2: Supports card, bank transfer, USSD, Opay/Palmpay
- [ ] AC-09.3: Success screen shown immediately on payment confirmation
- [ ] AC-09.4: Failure reason shown with a "Try again" option
- [ ] AC-09.5: Receipt sent via email/WhatsApp within 2 minutes
- [ ] AC-09.6: Package activated within 60 seconds of webhook receipt
- [ ] AC-09.7: Idempotent on processor reference — duplicate webhooks do not double-provision, regardless of which processor was used

Note: Processor primary/secondary order (Paystack primary, Flutterwave secondary) held as config (PAYMENT_PROCESSOR_PRIMARY / PAYMENT_PROCESSOR_SECONDARY), not hardcoded — adjustable post-launch on observed success rate/settlement speed/fees without a logic rewrite. Per docs/prd.md §5.3 (updated).
EOF
)" \
"priority-P0,type-feature,area-payments"

# ---------------------------------------------------------------------------
# US-10
create_issue \
"US-10 [P0]: eSIM device-compatibility check and warning" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** have the app check whether my device supports eSIM and warn me clearly if it does not **so that** I can make alternative arrangements before I travel.

Reference: docs/prd.md §4.4, §5.4

### Acceptance Criteria
- [ ] AC-10.1: On entering the eSIM setup screen, the app checks device eSIM capability (platform-specific — see §5.4)
- [ ] AC-10.2: If supported: proceed to download flow
- [ ] AC-10.3: If unsupported: warning modal with Continue / Support options
- [ ] AC-10.4: "Continue" proceeds without blocking
- [ ] AC-10.5: "Support" opens WhatsApp with a pre-filled order reference
- [ ] AC-10.6: Warning shown once, not repeated on subsequent opens
- [ ] AC-10.7: HTO dashboard flags eSIM-incompatible pilgrims with a "Follow up" label
EOF
)" \
"priority-P0,type-feature,area-esim"

# ---------------------------------------------------------------------------
# US-11
create_issue \
"US-11 [P0]: Pre-departure eSIM profile download + QR code" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** download my eSIM profile and receive a QR code before I depart **so that** I do not need internet access after landing.

Reference: docs/prd.md §4.4, §5.4

### Acceptance Criteria
- [ ] AC-11.1: Available from purchase, recommended window "2–7 days before departure"
- [ ] AC-11.2: On supported devices: "Download to device" initiates eSIM download via the aggregator API
- [ ] AC-11.3: QR code always generated and saveable as a fallback
- [ ] AC-11.4: Idempotent — repeated taps issue only one profile
- [ ] AC-11.5: Failed downloads queue and auto-retry, with notification on success
- [ ] AC-11.6: Download status visible to the HTO operator

Note: eSIM aggregator vendor ranking decided — Monty Mobile (primary), eSIM Access (secondary), 1Global (tertiary), with automatic failover through the ranked list on issuance failure. Vendor order held as config, not hardcoded, and expected to be revisited as real usage data comes in. Per docs/prd.md §5.4 (updated).
EOF
)" \
"priority-P0,type-feature,area-esim"

# ---------------------------------------------------------------------------
# US-12
create_issue \
"US-12 [P1]: Emergency contacts and key phrases (pre-departure)" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** see emergency contacts and key phrases before I depart **so that** I have them without needing internet, even without a map.

Reference: docs/prd.md §4.4

### Acceptance Criteria
- [ ] AC-12.1: Emergency essentials shown on the same pre-departure screen as eSIM QR/download (§5.4)
- [ ] AC-12.2: Includes the HTO operator's number, DamDam support WhatsApp, and a short set of key Arabic phrases (help, thank you, where is, I don't understand, I need a doctor)
- [ ] AC-12.3: Content is bundled directly in the app, not downloaded separately — always available offline, zero data cost, no download step, no map SDK or content-pack table needed
- [ ] AC-12.4: The same content is also reachable from the SOS screen for quick reference during an actual emergency, not just pre-departure

**Scope note:** This story originally covered full offline maps (Haram/Mina/Arafat POIs, a ≤50MB downloadable pack, in-app navigation). That was cut deliberately — it's P1, not a stated MVP goal (G1–G6), and largely redundant once a pilgrim's eSIM data is active, since their phone's own Maps app already covers wayfinding better than anything DamDam would build. What's kept is the narrow slice a phone's OS maps can't provide: emergency contacts and phrases that work with zero connectivity and zero setup.

**Data model:** Backed by the new `emergency_content` table in `docs/data-model.md`, keyed by `destination_country` — plain text/JSON only, no images, no map tiles. If this issue was already in progress against the old scope, please check with the team before continuing — the old AC-12.1 through AC-12.7 (offline map download, 50MB pack, progress bar) are no longer in scope.
EOF
)" \
"priority-P1,type-feature,area-offline"

# ---------------------------------------------------------------------------
# US-13
create_issue \
"US-13 [P0]: Low-friction eSIM activation prompt on arrival" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** receive a prompt to activate my eSIM with minimal friction after landing **so that** I have data within minutes of arrival.

Reference: docs/prd.md §4.5, §5.4

### Acceptance Criteria
- [ ] AC-13.1: Geofencing (150km radius, Jeddah) triggers a push notification on entry, where location permission is granted
- [ ] AC-13.2: Notification copy: "You've arrived in Saudi Arabia. Tap to activate your DamDam data — takes 30 seconds."
- [ ] AC-13.3: Tap deep-links to the activation screen
- [ ] AC-13.4: Android with carrier-privilege support: single-tap in-app profile switch with one system confirmation dialog
- [ ] AC-13.5: All iOS devices, and Android devices without carrier-privilege support: routes to a step-by-step manual guide (iOS has no public API for programmatic eSIM switching — this is the primary path for every iOS pilgrim)
- [ ] AC-13.6: Home screen shows "Saudi Arabia data — active" with remaining data once activated
- [ ] AC-13.7: If geofencing fails or permission denied: a persistent "Activate eSIM" banner appears from 7 days before the recorded departure date
EOF
)" \
"priority-P0,type-feature,area-esim"

# ---------------------------------------------------------------------------
# US-14
create_issue \
"US-14 [P0]: Verified-caller-ID outbound calling" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** make an outbound call showing my real Nigerian number **so that** my family picks up.

Reference: docs/prd.md §4.6, §5.5

### Acceptance Criteria
- [ ] AC-14.1: CLI verification (OTP) completed once at account setup
- [ ] AC-14.2: Dial pad + device contacts picker
- [ ] AC-14.3: Calls route over the eSIM data connection (VoIP)
- [ ] AC-14.4: Recipient sees the pilgrim's verified Nigerian number
- [ ] AC-14.5: Call quality indicator shown during the call
- [ ] AC-14.6: Dropped connectivity → graceful "Call ended — connectivity lost", not a silent freeze
- [ ] AC-14.7: PSTN minutes deducted in real time, balance updated within 60 seconds
- [ ] AC-14.8: App-to-app calls are free, shown clearly as such
- [ ] AC-14.9: Call history shows last 20 calls

Note: Voice vendor decided — Telnyx (per docs/prd.md §5.5, §6 Phase 0, updated). Build against a thin VoiceProvider abstraction, not a direct SDK call, per the updated §5.5 rationale. Future roadmap (post-MVP, not this issue's scope): BYOC migration planned — Telnyx stays as call-control/WebRTC layer, IDT Express added underneath as the PSTN termination backbone once call volume justifies wholesale rates. The VoiceProvider abstraction built here is what makes that migration low-risk later.
EOF
)" \
"priority-P0,type-feature,area-voice"

# ---------------------------------------------------------------------------
# US-15
create_issue \
"US-15 [P0]: One-tap check-in (offline-first)" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** send a check-in with a single tap **so that** my HTO and family know I am safe, even with poor connectivity.

Reference: docs/prd.md §4.6, §5.6

### Acceptance Criteria
- [ ] AC-15.1: "I'm okay" button, single tap, no confirmation dialog
- [ ] AC-15.2: Timestamp + GPS (if permitted) recorded on tap
- [ ] AC-15.3: Transmitted within 5 seconds if connected
- [ ] AC-15.4: If offline: queued locally, retried every 30s, UI shows "Check-in queued, will send when connected"
- [ ] AC-15.5: HTO dashboard updates last-seen status on success
- [ ] AC-15.6: Family contact receives WhatsApp: "[Name] checked in safely at [time]. All is well."
- [ ] AC-15.7: Includes a Google Maps link if location available
- [ ] AC-15.8: Pilgrim sees "Check-in sent" confirmation
- [ ] AC-15.9: Rate-limited to one per 15 minutes
- [ ] AC-15.10: If the WhatsApp notification to the family contact fails or does not confirm delivery within 60 seconds, an SMS with equivalent content is sent automatically as a fallback

Note: WhatsApp/SMS fallback per docs/prd.md §5.6 (updated). Channel order and 60s window held as config (FAMILY_NOTIFY_CHANNEL_PRIMARY / FAMILY_NOTIFY_CHANNEL_SECONDARY), adjustable post-launch without a logic rewrite. SMS fallback reuses the configured primary OTP provider (§5.1) rather than a separate vendor.
EOF
)" \
"priority-P0,type-feature,area-safety"

# ---------------------------------------------------------------------------
# US-16
create_issue \
"US-16 [P0]: SOS emergency alert" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** trigger an SOS that immediately notifies my HTO and family with my location **so that** I can get help in an emergency.

Reference: docs/prd.md §4.6, §5.6

### Acceptance Criteria
- [ ] AC-16.1: Red "SOS / Emergency" button, visually distinct from check-in
- [ ] AC-16.2: 3-second press-and-hold with visual countdown
- [ ] AC-16.3: On confirmed SOS: stored locally first, then server notified (queued if offline); HTO gets push + dashboard alert + email + WhatsApp; family gets an URGENT WhatsApp message with location link and the HTO's direct number
- [ ] AC-16.4: "SOS sent — help is coming" screen with the HTO's number as a native-dialer "Call now" button
- [ ] AC-16.5: SOS cannot be accidentally cancelled — separate "Cancel SOS" button with confirmation
- [ ] AC-16.6: Cancellation sends a follow-up notification to both channels
- [ ] AC-16.7: No rate limit on SOS
EOF
)" \
"priority-P0,type-feature,area-safety"

# ---------------------------------------------------------------------------
# US-17
create_issue \
"US-17 [P1]: Home-screen data & minutes balance display" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** see my remaining data and minutes on the home screen **so that** I know when to top up.

Reference: docs/prd.md §4.6, §5.7

### Acceptance Criteria
- [ ] AC-17.1: Persistent status cards for data and minutes
- [ ] AC-17.2: Updates within 60 seconds of a usage event
- [ ] AC-17.3: Yellow warning below 20% data / 5 minutes voice
- [ ] AC-17.4: Red warning at zero
- [ ] AC-17.5: Add-ons handled via WhatsApp support for MVP (no in-app purchase flow yet)
- [ ] AC-17.6: Values remain visible offline (last cached)
EOF
)" \
"priority-P1,type-feature,area-usage"

# ---------------------------------------------------------------------------
# US-18
create_issue \
"US-18 [P0]: HTO dashboard — pilgrim check-in status overview" \
"$(cat <<'EOF'
**As an** HTO Operator, **I want to** see the check-in status of all my pilgrims at a glance.

Reference: docs/prd.md §4.7, §5.8

### Acceptance Criteria
- [ ] AC-18.1: Default view sorted by risk — unresolved SOS first, then stale check-ins, then alphabetical
- [ ] AC-18.2: Each row: name, phone, tier, eSIM status, last check-in
- [ ] AC-18.3: >24h since check-in → amber highlight
- [ ] AC-18.4: Unresolved SOS → red highlight, pinned to top
- [ ] AC-18.5: Auto-refresh every 60s + manual refresh
- [ ] AC-18.6: Filter by manifest
- [ ] AC-18.7: Search by name or phone
EOF
)" \
"priority-P0,type-feature,area-dashboard"

# ---------------------------------------------------------------------------
# US-19
create_issue \
"US-19 [P0]: HTO SOS alert channels" \
"$(cat <<'EOF'
**As an** HTO Operator, **I want to** get immediate alerts on any SOS **so that** I can respond without checking the dashboard.

Reference: docs/prd.md §4.7

### Acceptance Criteria
- [ ] AC-19.1: Browser push notification
- [ ] AC-19.2: Email within 60 seconds
- [ ] AC-19.3: WhatsApp message
- [ ] AC-19.4: All three fire regardless of dashboard session state
- [ ] AC-19.5: Operator can mark "Resolved", clearing the highlight
- [ ] AC-19.6: Resolved SOS sends no further notifications
EOF
)" \
"priority-P0,type-feature,area-dashboard,area-safety"

# ---------------------------------------------------------------------------
# US-20
create_issue \
"US-20 [P1]: HTO provisioning report download" \
"$(cat <<'EOF'
**As an** HTO Operator, **I want to** download a provisioning report for my own records and NAHCON compliance.

Reference: docs/prd.md §4.7

### Acceptance Criteria
- [ ] AC-20.1: CSV download
- [ ] AC-20.2: Per-pilgrim: name, phone, tier, purchase date, eSIM status, check-in count, SOS events
- [ ] AC-20.3: Filterable by manifest and date range
- [ ] AC-20.4: Generated within 30 seconds for manifests up to 500 rows
EOF
)" \
"priority-P1,type-feature,area-dashboard"

# ---------------------------------------------------------------------------
# US-21
create_issue \
"US-21 [P0]: Family WhatsApp notification on check-in" \
"$(cat <<'EOF'
**As a** Family Contact, **I want to** receive a WhatsApp message when my pilgrim checks in **so that** I know they're safe without calling.

Reference: docs/prd.md §4.8

### Acceptance Criteria
- [ ] AC-21.1: Sent from a consistent DamDam WhatsApp Business number
- [ ] AC-21.2: Plain English, no jargon
- [ ] AC-21.3: Delivered within 60 seconds of server receipt
EOF
)" \
"priority-P0,type-feature,area-safety"

# ---------------------------------------------------------------------------
# US-22
create_issue \
"US-22 [P0]: Family WhatsApp notification on SOS" \
"$(cat <<'EOF'
**As a** Family Contact, **I want to** receive a WhatsApp message when my pilgrim triggers an SOS **so that** I know immediately.

Reference: docs/prd.md §4.8

### Acceptance Criteria
- [ ] AC-22.1: Message begins with "URGENT:"
- [ ] AC-22.2: Includes the HTO operator's direct phone number
- [ ] AC-22.3: If the WhatsApp SOS notification to the family contact fails or does not confirm delivery within 60 seconds, an SMS with equivalent content is sent automatically as a fallback

Note: WhatsApp/SMS fallback per docs/prd.md §5.6 (updated). Channel order and 60s window held as config (FAMILY_NOTIFY_CHANNEL_PRIMARY / FAMILY_NOTIFY_CHANNEL_SECONDARY), adjustable post-launch without a logic rewrite. This is the highest-priority fallback gap identified — SOS notification to family should not have a single point of failure.
EOF
)" \
"priority-P0,type-feature,area-safety"

# ---------------------------------------------------------------------------
# US-23
create_issue \
"US-23 [P0]: Persistent session & local PIN unlock" \
"$(cat <<'EOF'
**As a** Pilgrim, **I want to** stay signed in without repeated logins, especially without internet.

Reference: docs/prd.md §4.9

### Acceptance Criteria
- [ ] AC-23.1: Session tokens stored in platform secure storage (Android Keystore / iOS Keychain)
- [ ] AC-23.2: Session persists 30 days of inactivity
- [ ] AC-23.3: PIN required after 5 minutes backgrounded, validated locally (no network call needed)
- [ ] AC-23.4: Full re-authentication only on a new device or after 30 days
- [ ] AC-23.5: Offline features (maps, SOS queue, PIN unlock) work without any server connection
EOF
)" \
"priority-P0,type-feature,area-auth"

# ---------------------------------------------------------------------------
# US-24
create_issue \
"US-24 [P0]: Offline-first check-in/SOS queueing" \
"$(cat <<'EOF'
**As the** System, **I want to** queue check-in and SOS events locally and transmit on reconnect **so that** safety data is never lost to network congestion at Mina or Arafat.

Reference: docs/prd.md §4.10, §5.6

### Acceptance Criteria
- [ ] AC-24.1: Local write before any network attempt
- [ ] AC-24.2: Background retry every 30s while queued
- [ ] AC-24.3: Not removed from queue until server 200 response
- [ ] AC-24.4: Queue persists across app restarts/reboots
- [ ] AC-24.5: Home screen shows "X event(s) waiting to send"
EOF
)" \
"priority-P0,type-feature,area-offline,area-safety"

# ---------------------------------------------------------------------------
# US-25
create_issue \
"US-25 [P0]: Idempotent duplicate-package prevention" \
"$(cat <<'EOF'
**As the** System, **I want to** prevent duplicate package provisioning.

Reference: docs/prd.md §4.10, data-model.md §6.7

### Acceptance Criteria
- [ ] AC-25.1: Payment webhook references checked for idempotency, regardless of which processor (Paystack or Flutterwave) issued the transaction
- [ ] AC-25.2: HTO activation codes single-use
- [ ] AC-25.3: One active package per destination per trip period
- [ ] AC-25.4: Duplicate attempts logged for admin review, no visible user-facing error
EOF
)" \
"priority-P0,type-feature,area-payments"

# ---------------------------------------------------------------------------
# US-26
create_issue \
"US-26 [P1]: Manual admin-triggered Naira pricing" \
"$(cat <<'EOF'
**As an** Admin, **I want to** manually update Naira package prices from the dashboard **so that** pricing can be adjusted when the exchange rate moves, without a live FX API dependency or a daily automated job.

Reference: docs/prd.md §4.10, §5.9

### Acceptance Criteria
- [ ] AC-26.1: Admin screen shows the current Naira price per tier, editable
- [ ] AC-26.2: Updated price takes effect immediately for new purchases; in-progress checkouts already underway are unaffected
- [ ] AC-26.3: Price change requires confirmation showing the % change from the current price — a lightweight version of the original guardrail, surfaced to the admin rather than blocking automatically
- [ ] AC-26.4: Every price change is logged (admin, timestamp, old value, new value) for audit purposes
- [ ] AC-26.5: No live FX API dependency, no scheduled job — this is a fully manual, on-demand action

### Scope note

This story originally specified a fully automated daily NFEM-indexed pricing job. It has been scaled down to manual admin-triggered repricing: the Naira has been comparatively stable under the CBN's reformed NFEM framework (~1-2% monthly movement), and package costs are USD-denominated against fixed-Naira revenue, so a live FX dependency and scheduled job are not worth building for pre-launch volatility. Revisit automating this (daily job, rate-change guardrail, admin alerting) if the Naira becomes meaningfully more volatile later.
EOF
)" \
"priority-P1,type-feature,area-payments"

echo ""
echo "Done. 26 issues created (if no errors above)."
