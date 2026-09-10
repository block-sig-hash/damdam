# Frontend Specification — Mobile App

> **Current scope:** the September 2026 reset in §8.9 and
> [PRD §10](prd.md) governs conflicts with earlier text. Use the
> [scope disposition](implementation/SCOPE-DISPOSITION.md) and
> [decision register](implementation/DECISIONS.md) for retained, retired
> and proposed behavior. These are target requirements; existing code and
> supported transition paths remain subject to their applicable checks.

# DamDam — Version 0.1 · React Native · iOS + Android

Single React Native codebase targeting both platforms at MVP.
Platform divergence is called out explicitly wherever it exists —
primarily in the eSIM activation flow, where iOS has no public API
for programmatic eSIM installation or switching, and every iOS
pilgrim is therefore routed through a manual guide (not a fallback
path — the primary and only path on iOS).

---

## 8.1 Screen Inventory

**Onboarding & Auth**
1. Splash
2. Phone Number Entry
3. OTP Verification
4. PIN Setup
5. Family Contact Setup
6. Departure Date Entry
7. Home (post-onboarding, no package yet)

**Purchase**
8. Package Selection
9. Family Group Size Selector (modal, conditional)
10. Paystack Checkout (web view)
11. Purchase Success
12. Purchase Failure

**Activation Flow (HTO-sourced pilgrims only)**
13. Activation Code Entry
14. Activation Success

**eSIM Setup**
15. eSIM Setup Intro
16. Device Compatibility Warning (modal, conditional)
17. eSIM QR Code Display
18. eSIM Activation Prompt (banner + full screen)
19. eSIM Activation Guide (platform- and device-specific steps)

**Offline Pack**
20. Offline Pack Download

**Home (post-package)**
21. Home Dashboard

**Calling**
22. Dial Pad
22a. Verified Caller ID — Enter Number
22b. Verified Caller ID — Enter Code
22c. Verified Caller ID — Consent
22d. Verified Caller ID — Manage (status/revoke/lost-SIM; reachable from
     Dial Pad, doubles as the resume point for an interrupted 22a-22c flow)
23. Active Call
24. Call History

**Safety**
25. Check-in Confirmation (inline, not full screen)
26. SOS Hold-to-Confirm
27. SOS Sent Confirmation
28. SOS Cancel Confirmation

**Account**
29. Settings
30. Package Details / Usage
31. PIN Unlock (app-open gate)

**Support**
32. WhatsApp Support Handoff (external deep link, documented as a
    navigation endpoint, not an in-app screen)

---

## 8.2 User Flow Diagrams

### Flow A: Direct Signup → First Call (happy path)

```
Splash
  → Phone Entry → OTP → PIN Setup → Family Contact
  → Departure Date
  → Home (no package)
  → Package Selection → [Family? → Group Size] → secure checkout
  → Purchase Success
  → eSIM Setup Intro
    → [compatible?] → QR/Download → Offline Pack
    → [incompatible] → Warning Modal → Continue → QR only
  → Home (package active, eSIM pending activation)
  ... time passes, pilgrim travels ...
  → [geofence OR date banner] → eSIM Activation Prompt
  → Activation Guide (manual on iOS always; manual on Android
    without carrier-privilege support; in-app switch on
    carrier-privilege-capable Android)
  → Home (data active)
  → Dial Pad → Active Call → Call History
```

### Flow B: HTO-Activated Pilgrim

```
[WhatsApp message received externally]
  → Deep link opens app → Activation Code Entry
    → [not registered] → Phone Entry → OTP → PIN Setup
      → Family Contact → Departure Date
    → [already registered, valid local session] → PIN Unlock
    → [already registered, no valid local session — new device,
      or session older than 30 days, AC-23.4] → Returning Pilgrim
      (OTP-based re-authentication; not PIN entry — PIN is a
      local-only unlock gate per AC-23.5, there is no phone+PIN
      login endpoint, so this reuses US-02's OTP recovery pair)
  → Activation Success (package already attached, skip
    Package Selection and Paystack entirely)
  → eSIM Setup Intro
  ... converges with Flow A from here ...
```

### Flow C: Emergency (SOS)

```
Home (any state, package active)
  → Press + hold SOS button (3s, visual countdown)
  → SOS Sent Confirmation (shows HTO contact number)
  → [optional] Cancel Confirmation → back to Home
```

### Flow D: Check-in (lightweight, no full-screen flow)

```
Home → tap "I'm okay" → inline confirmation toast/banner
       (no navigation away from Home)
```

---

## 8.3 Per-Screen Specifications

### Screen: Home Dashboard (Screen 21)

**Purpose:** Single most-visited screen. Everything a pilgrim
needs is one tap away.

**Data displayed:**
- Package status card: tier name, data remaining (GB, progress
  bar), PSTN minutes remaining (progress bar)
- eSIM status badge: "Not activated" / "Ready to activate" /
  "Active"
- Last check-in timestamp
- Queued events indicator (if offline queue non-empty)

**Interactive elements:**
- "I'm okay" button — large, primary, top of screen
- "SOS / Emergency" button — red, requires press-and-hold
- "Call" quick action → Dial Pad
- Package status card → tap → Package Details
- eSIM status badge → tap → eSIM Setup flow or Package Details
- Bottom tab bar: Home / Call / Safety History / Settings

**States:**
- *Loading:* skeleton screens, cached data shown immediately,
  refresh in background (offline-first)
- *No package yet:* "Get connected" CTA → Package Selection
- *Offline:* cached data shown normally; queued-events indicator
  visible; Call action shows disabled state, "Requires connection"
- *Data/minutes low (<20%):* yellow banner
- *Data/minutes exhausted:* red banner
- *eSIM incompatible flagged:* persistent info banner linking to
  WhatsApp support

**Platform note:** No divergence — this screen is identical on
iOS and Android.

---

### Screen: Package Selection (Screen 8)

**Data displayed:** Four tier cards (Starter, Basic, Standard,
Family), each with name, NGN price, data GB, PSTN minutes, 3
feature bullets. Standard has a "Recommended" badge. Family shows
"From ₦X" with a group-size selector triggered on tap.

**Interactive elements:**
- Tier card tap → non-Family: proceeds directly to secure checkout.
  Family: opens Group Size Selector modal first.
- "What's included" expandable accordion

**States:**
- *Loading:* skeleton cards
- *Error (pricing fetch fails):* full-screen error with retry —
  deliberately no fallback to stale client-cached prices here,
  since showing a wrong Naira price on a real purchase is worse
  than a blocking error

---

### Screen: Family Group Size Selector (Screen 9, modal)

**Data displayed:** Stepper (2–8), live-recalculating total price
as size changes (data-model.md §6.4).

**Interactive elements:**
- Stepper +/− or direct numeric entry
- "Continue" → secure checkout with `group_size` in the purchase payload
- Dismiss (X) → returns to Package Selection

### Screen: Payment Checkout (Screen 10)

**Data displayed:** A processor-neutral heading and the supported Naira rails
(card, bank transfer, USSD, OPay and PalmPay), followed by the backend-provided
`checkout_url` in an inline web view. Paystack/Flutterwave branding may appear
inside their hosted page, but DamDam never renders a processor selector or
processor-specific app controls.

**Interactive elements:** Hosted payment controls inside the web view. Package
status polling begins immediately and repeats every 10 seconds for at most five
minutes, so a delayed redirect cannot hide a webhook-confirmed purchase.

**States:** Preparing checkout; hosted checkout; processor-declared failure or
web-view load failure with the reason and "Try again"; delayed confirmation
with contact-support guidance after five minutes; webhook-confirmed success
routing immediately to Purchase Success.

### Screen: Purchase Success (Screen 11)

**Data displayed:** Success confirmation, activated data/minutes balances, and
a receipt-delivery note. This state is shown only after the API reports the
package `active`, never from a hosted-page redirect alone.

**Interactive elements:** "Continue" advances to the eSIM setup path.

---

### Screen: eSIM Setup Intro (Screen 15)

**Purpose:** First checkpoint after purchase. Runs the device
compatibility check silently on screen load.

**Flow logic — platform-specific:**
- **Android:** calls `EuiccManager.hasEuicc()`. Compatible →
  "Download to device" primary CTA + "Show QR code instead"
  secondary. Incompatible → Device Compatibility Warning modal
  fires automatically.
- **iOS:** there is no capability API to call. Device model is
  checked against a maintained known-eSIM-supported-models list
  (iPhone XS and later, generally). If the model is on the list:
  proceed to QR display + "Install eSIM" instructions (iOS always
  shows the manual guide, never an in-app switch — see Screen 19).
  If not on the list: Device Compatibility Warning modal fires.

**States:**
- *Checking device:* brief loading state (local check, <1s
  expected on both platforms)
- *Compatible:* proceed as above (with platform-specific CTA
  wording — Android may offer in-app download, iOS always
  presents the QR/manual path)
- *Incompatible:* modal shown once, then this screen shows
  QR-only view on subsequent visits

---

### Screen: Device Compatibility Warning (Screen 16, modal)

**Content:** *"Your device does not appear to support eSIM. You
can still use your DamDam package by scanning the QR code on a
compatible device. Tap Continue to download your QR code, or tap
Support to get help."* Two buttons: "Continue" (proceeds to QR
display) and "Support" (WhatsApp deep link, pre-filled order
reference).

**Behavioural note:** Fires `POST /me/device-compatibility`
(`platform`, `device_model`, `os_version`) on detection — i.e. as
soon as the check on Screen 15 comes back unsupported, before this
modal is even shown, same as the compatible path. This is
deliberate: AC-10.7's HTO follow-up flag has to be set for every
genuinely incompatible pilgrim, including one who backgrounds or
force-quits the app after seeing the warning without tapping
Continue or Support — deferring the log to that action would leave
exactly that pilgrim (the one who didn't engage further) unflagged.
Continue/Support/back-gesture only mark the warning as shown
(AC-10.6, so it isn't repeated) — they do not log a second time.

---

### Screen: eSIM QR Code Display (Screen 17)

**US-11 implementation assumption:** This screen previously appeared only in
the inventory, with no data/elements/states specification. Until product/design
provides a fuller per-screen treatment, the minimal implementation uses the
existing design-system tokens and the US-11 acceptance criteria directly.

**Data displayed:** recommended installation window (2–7 days before
departure), lifecycle status, a large vendor-hosted QR image, ICCID, and the LPA
activation code as selectable text fallback.

**Interactive elements:** Android “Download to device” invokes the native
`EuiccManager` bridge and disables while in flight; iOS stays on the QR/manual
path and offers a self-reported “I installed this eSIM” action; “Save QR code”
opens the full-resolution image in the OS viewer so the user can use Save Image.

**States:** preparing; ready; download in progress; downloaded; and failed/
queued. The queued state explains automatic retry, offers an immediate manual
retry, polls the idempotent issuance endpoint, and tells the pilgrim they may
leave because WhatsApp will notify them when the QR is ready.

**US-12 addition:** the `EmergencyEssentials` component renders below the
eSIM content once it's loaded (AC-12.1) — the HTO operator's number (read
live per-pilgrim, hidden entirely for a direct/retail pilgrim with none),
DamDam's support WhatsApp number, and the five bundled Arabic key phrases
(help, thank you, where is, I don't understand, I need a doctor), each
shown as English label + Arabic script (right-to-left) + Latin
transliteration. It's a bordered card of its own, visually separated from
the QR/detail cards above rather than merged into them. It only renders
on the loaded (ready/downloaded) screen state, not on the transient
preparing/queued states — an explicit scope choice, not an oversight,
since those states have no eSIM content of their own to be "alongside"
yet either.

**AC-12.4 deferral:** the same content is also supposed to be reachable
from the SOS screen for quick reference during an actual emergency — the
SOS screens (`SosConfirm`/`SosSent`) don't exist yet (US-16, Phase 3).
`EmergencyEssentials` is built as a screen-agnostic, reusable component
(it only needs an `accessToken` prop) specifically so it can be dropped
into the future SOS screen without rework, once that screen exists. This
is a forward-compatibility decision, not a skipped requirement.

---

### Screen: eSIM Activation Prompt

**Two variants:**

*Variant A — Persistent banner (primary, date-triggered, both
platforms):* Appears on Home Dashboard starting 7 days
pre-departure, non-modal, dismissible per-session but reappears on
next open until eSIM status = activated.

*Variant B — Push-triggered full screen (secondary, geofence-
triggered, opt-in, both platforms via React Native Firebase +
platform-native geofencing/region-monitoring):* Only fires if
location permission granted. Deep-links from the push directly
into the activation flow.

**Interactive elements — platform-specific:**
- **Android, carrier-privilege-capable devices:** "Activate now"
  triggers the in-app eSIM switch (single system confirmation
  dialog).
- **Android, non-privileged devices, and every iOS device:**
  "Activate now" routes to the Activation Guide (Screen 19). This
  is the majority path across the whole user base, not an edge
  case — build and test it as the primary flow, not a fallback.

---

### Screen: eSIM Activation Guide (Screen 19)

**Purpose:** Device- and platform-specific manual walkthrough.
This is the primary activation path for all iOS pilgrims and most
Android pilgrims (only carrier-privilege-capable Android devices
skip this screen).

**Data displayed:**
- **Android:** numbered steps with screenshots, selected by
  matching the logged `device_model` against a content library
  (Tecno Camon/Spark, Infinix Hot/Note, itel, Samsung Galaxy
  A-series), falling back to a generic Android guide if unmatched.
- **iOS:** a single, consistent guide (Settings → Cellular → Add
  eSIM → scan the in-app QR code), since Apple's eSIM installation
  UI is stable across supported iPhone models — far less content
  variation needed than Android.

**Content production note (build task, not just engineering):**
The Android guide library (10–15 device models) and the single iOS
guide together form a content workstream that should be scoped
explicitly into the build timeline, ideally produced and tested on
real physical devices from the target demographic's actual device
mix rather than emulators.

**US-13 implementation status:** The matching and generic-fallback UI shell is
implemented for Tecno Camon/Spark, Infinix Hot/Note, itel, and Samsung Galaxy
A-series. The Android family entries intentionally use labelled placeholder
frames until the production screenshots are captured and verified on those
physical devices; this content work remains a pre-ship requirement, not an
engineering fallback silently presented as final artwork.

---

### Screen: Dial Pad (Screen 22)

**Data displayed:** Numeric keypad, contact picker icon (device
contacts), recent-calls quick access.

**Interactive elements:**
- Number entry
- Contact picker → device contact list (iOS: `Contacts` framework
  permission; Android: `READ_CONTACTS` — both requested
  contextually when this icon is first tapped, not at app launch)
- Call button — disabled with tooltip if 0 PSTN minutes AND the
  number isn't a known DamDam user (app-to-app remains available
  regardless of PSTN balance)

**States:**
- *No connectivity:* Call button disabled, banner: "Calling
  requires an internet connection"
- *Low minutes (<5):* warning banner, does not block
- *`cli_not_verified` eligibility reason (AC-14.1):* Call button
  disabled for the PSTN case, `info`-tone banner ("Verify your
  Nigerian number to call numbers outside DamDam.") with a "Verify
  now" trailing action opening Screen 22d. App-to-app remains
  unaffected. A persistent low-emphasis "Caller ID" text link in the
  header opens Screen 22d regardless of verification state.

---

### Screens: Verified Caller ID (Screens 22a–22d)

**Added by the US-14 CLI-hardening amendment**
(`verified-cli-scoping.md` §5, `data-model.md` §6.40) — no prior spec
existed for these screens, so this section is new rather than a
revision. AC-14.1/AC-14.10/AC-14.11.

**Screen 22a — Enter Number.** Same input pattern as Phone Number
Entry (Screen 2): single Nigerian-number text field, `Send code`
primary button disabled until valid, `Not now` tertiary link back to
Dial Pad. Deliberately **not** pre-filled with the account's login
number (AC-14.10) — a pilgrim may verify possession of any Nigerian
mobile number here.

**Screen 22b — Enter Code.** Same six-box code-entry component as
OTP Verification (Screen 3), reused rather than re-invented. Wrong
code shows an inline error and does not clear the input; a
provider-rate-limit response (too many wrong attempts against this
verification) disables further submission with a warning-tone
message. `Use a different number` link returns to Screen 22a.

**Screen 22c — Consent.** Explicit, versioned consent copy stating
the number is now used as caller ID and that revocation/lost-SIM
reporting is always available and takes effect immediately without
affecting an in-flight call. Single `Agree and activate` primary
button — no separate opt-out control on this screen itself (that
lives in Screen 22d after activation).

**Screen 22d — Manage.** The single entry point for both first-time
verification and ongoing management, rather than a separate settings
screen (no `apps/mobile` Settings screen exists yet to host this).
Data displayed depends on state:
- *No identity yet:* explanation + `Verify a number` button (opens
  Screen 22a).
- *Mid-verification (`phone_verification_pending` /
  `consent_required`):* resumes directly at Screen 22b or 22c rather
  than restarting.
- *`active`:* verified number in a card with a "Verified" status
  pill, `Verify a different number` (secondary button, opens Screen
  22a — activating a new number automatically revokes the old one),
  `Revoke` and `Report lost SIM` (destructive buttons). Per
  `design-system.md` §7's "always a custom in-app modal, never a
  native alert" rule, both destructive actions reveal an inline
  confirmation (not a native `Alert`) before calling the API.

---

### Screen: Active Call (Screen 23)

**Data displayed:** Recipient number/name, duration timer, call
type indicator ("DamDam-to-DamDam — free" or standard), signal
quality indicator, mute/speaker/end-call controls.

**States:**
- *Connecting:* brief loading state
- *Connected:* timer running, controls active
- *Connectivity lost mid-call:* graceful termination, "Call ended
  — connectivity lost", auto-navigates back to Dial Pad after 3s

**Platform note:** Both platforms report calls to their native call UI,
implemented in two separate PRs against this same spec --
`apps/mobile/ios/DamDam/AppDelegate.swift` (iOS, CallKit + PushKit)
and `apps/mobile/android/app/src/main/java/com/damdam/app/
CallHeadlessTaskService.kt` (Android, ConnectionService), both wired
through the shared `src/services/callKit.ts`. On iOS, PushKit wakes
the app for an incoming call even when backgrounded or killed; on
Android the equivalent is FCM detecting an incoming-call-shaped data
message and starting a Headless JS Task, per react-native-callkeep's
own documented recommendation for this exact scenario. **A real,
disclosed limitation specific to Android**: `RNCallKeep.setup()` (and
the phone-account permission it requests) only runs once the user has
opened Dial Pad at least once (`DialPadScreen.tsx`'s mount effect,
matching this app's existing contextual-permission convention) --
until then, an incoming call cannot display via ConnectionService on
that device at all. iOS has no equivalent gap; CallKit setup happens
unconditionally and silently at session start.

---

### Screen: SOS Hold-to-Confirm (Screen 26)

**Purpose:** Deliberately friction-full to prevent accidents,
while fast enough for genuine emergencies.

**Interactive elements:**
- Large red button, press-and-hold gesture, 3-second visual
  countdown ring
- Release before 3s → cancels silently, no action taken, no log
  entry (avoids noise from ordinary mis-taps)
- Hold completes → immediate transition to SOS Sent Confirmation;
  local write happens synchronously before the screen transition

---

### Screen: SOS Sent Confirmation (Screen 27)

**Data displayed:** Confirmation message, HTO operator's phone
number as a large tappable "Call now" button — invokes the
device's **native dialer** (not the app's VoIP layer), so it works
even if the app's calling feature is degraded. Timestamp of the
SOS.

**States:**
- *Sync pending (offline):* "Sending... will notify your operator
  and family as soon as you have signal" — this state persists
  visibly rather than showing a false "sent" confirmation before
  the queue has actually transmitted
- *Synced:* "Your operator and family have been notified"

---

### Screen: PIN Unlock (Screen 31, app-open gate)

**Purpose:** AC-02.3/AC-23.3 — re-entering the PIN after the app has
been backgrounded, validated entirely on-device (no network call).
The server's bcrypt `pin_hash` is never transmitted back to the
client (`prd.md` §5.1), so this compares against a separate,
locally-stored credential written to platform secure storage
(Android Keystore / iOS Keychain, `frontend-mobile.md` §8.7) at the
moment PIN Setup succeeds — see `data-model.md`/mobile client note
in that screen's implementation.

**Interactive elements:**
- 4-digit masked entry, same `OtpCodeInput` box pattern PIN Setup
  uses (`design-system.md` §4)
- AC-02.4/AC-23.5: 5 failed attempts locks entry for 30 minutes,
  countdown shown inline; "Forgot your PIN? Verify via OTP" is
  offered immediately (not only after lockout), reusing the
  existing OTP-recovery screen (Returning Pilgrim,
  `useReturningPilgrimLogin`) rather than a separate flow —
  recovery requires network access (it's an OTP round-trip), which
  doesn't conflict with the *routine* unlock path's offline
  requirement
- A device with no locally-stored PIN (never completed PIN Setup on
  this device, or a returning pilgrim's new-device login per
  AC-23.4) routes straight to OTP recovery instead of showing a PIN
  box with no possible correct answer

**Session-persistence wiring:** the layer that decides *when* to
show this screen — AC-23.1 secure token storage, AC-23.2 30-day
session, background-timer detection — is `useSessionGate`
(`apps/mobile/src/hooks/useSessionGate.ts`), wired into `App.tsx`
above `OnboardingNavigator`/`AuthenticatedApp`. This screen remains
a self-contained, testable unit; `useSessionGate` is what actually
invokes it, on both a cold start with a still-valid persisted
session and a foreground resume past the 5-minute background
threshold.

---

## 8.4 Navigation Structure

**Bottom tab bar (persistent once a package exists):** Home | Call
| Safety History | Settings

**Pre-package state:** No tab bar; single-flow navigation from
onboarding through first purchase.

**Modal vs. stack navigation:**
- Modals: Family Group Size Selector, Device Compatibility
  Warning, SOS Cancel Confirmation
- Stack (back-navigable): all onboarding screens, Package
  Selection, eSIM flow, Dial Pad → Active Call, Dial Pad ↔ Verified
  Caller ID Manage (22d) → Enter Number (22a) → Enter Code (22b) →
  Consent (22c) → back to Dial Pad on activation
- Non-dismissible full-screen: SOS Hold-to-Confirm once triggered
  → Sent Confirmation (must actively choose Cancel)

---

## 8.5 Offline Behaviour Summary

| Screen | Offline behaviour |
|---|---|
| Home Dashboard | Fully functional with cached data |
| Check-in | Fully functional (queues locally) |
| SOS | Fully functional (queues locally, higher retry priority) |
| Package Details | Cached data shown with "last updated" label |
| Dial Pad / Calling | Disabled, clear messaging |
| Package Selection / Purchase | Disabled, requires connection |
| eSIM QR Code | Fully functional (static, cached) |
| Offline Pack content | Fully functional by design |
| Settings (non-payment fields) | Fully functional, syncs on reconnect |

---

## 8.6 Push Notification Inventory

| Notification | Trigger | Tap action |
|---|---|---|
| eSIM activation reminder | Geofence entry (opt-in) | Deep-link to Activation Prompt |
| Low data warning | Balance < 20% | Deep-link to Home |
| Low minutes warning | Balance < 5 min | Deep-link to Home |
| Purchase confirmation | Payment webhook success | Deep-link to Purchase Success / Home |
| Package expiring soon | 24h before `expires_at` | Deep-link to Home |
| SOS sync confirmation | Queued SOS successfully transmitted | Deep-link to SOS Sent Confirmation |

**Platform delivery note:** React Native Firebase (FCM) handles
Android natively; iOS delivery routes through APNs via the same
Firebase abstraction layer, requiring an Apple Push Notification
service key configured in the Apple Developer account (see
infrastructure.md §11.4/§11.8).

---

## 8.7 Platform-Specific Build Considerations Summary

| Concern | Android | iOS |
|---|---|---|
| eSIM programmatic switching | Available on carrier-privilege-capable devices | **Never available** — no public API |
| eSIM capability check | `EuiccManager.hasEuicc()` | Device-model allowlist (no API) |
| Secure token storage | Android Keystore | iOS Keychain |
| Background sync (offline queue) | WorkManager | BGTaskScheduler |
| Push notifications | FCM native | FCM via APNs bridge, requires Apple Push key |
| Contacts permission | `READ_CONTACTS` | `Contacts` framework authorization |
| Native call UI integration | ConnectionService -- **built** (Headless JS Task + FCM wake), `CallHeadlessTaskService.kt` -- higher residual uncertainty, unverified without a physical device | CallKit + PushKit -- **built**, `src/services/callKit.ts` |
| Distribution | Google Play (internal testing → production track) | TestFlight (pilot) → App Store (production) |
| Review process predictability | Generally faster, more predictable | Can be slower and less predictable — build extra buffer into the timeline, see prd.md §6 |

---

## 8.8 Amendment — English/French Rendering

Every user-facing screen, state, accessibility label, offline fallback, and
native arrival/call notification renders through the bundled resources in
`localization.md`. Saved account locale wins over device inference; language
remains explicitly selectable during pre-account flows.

The offline Arabic phrasebook keeps Arabic speech text and transliteration
unchanged while localizing its explanatory UI. The screenshot matrix captures
English and French variants, including Android automatic eSIM activation and
the iOS manual guide. Final French safety/legal copy and real localized OS
walkthrough imagery remain release gates in `localization.md` §§6–7.

---

## 8.9 Amendment — Product Reset Supersedes the Hajj Mobile Scope

**Recorded 8 September 2026 by build chunk 01. Registered story: US-27.**
Documentation only — no screen or component change here.

`prd.md` §10 resets the app to four surfaces: **Home, Plans, My Line, Account**.
The SOS, family-nomination, arrival-geofence, verified-CLI and departure-date
screens leave launch scope in chunk 04; chunks 18–21 build the replacement.
Remaining check-in screens follow the proposed product-default disposition; do
not treat that proposal as an already completed removal. `prd.md` §10.3 holds the revised journeys.

Requirements that carry forward unchanged:

- Offline-first behavior for what remains — secure installation details and a
  timestamped last-known usage reading stay available offline. Do not weaken the
  write-before-network pattern to simplify a feature.
- Complete English and French coverage on every new surface.
- Accessibility and rendered-state review, including error, loading and empty
  states.

Requirements that change:

- Ordinary carrier calling needs **no** background location, contacts access or
  microphone permission. Release builds must not request permissions the product
  no longer uses (`US-30`, AC-30.5).
- Native voice runs through the phone's own dialer on the carrier eSIM. App
  calling is not the launch mechanism, so CallKit/PushKit app-call surfaces leave
  the launch dependency graph.
- Installation guidance must be real for the supported launch device matrix with
  a QR fallback; no placeholder guide ships (`US-38`, AC-38.1).
- The screen and locale screenshot matrix is re-cut in chunk 08 and enforced in
  chunk 27. Neither the historical 0/32 count nor the 32 images observed on
  2026-09-08 carries forward — both describe the old matrix.

---

## 8.10 Amendment — Offline Queues Are Owned by an Account (US-30, AC-30.4)

**Recorded 9 September 2026 by build chunk 04, subchunk 04A.**

The offline check-in and SOS queues previously stored no owner. Both tables
lived in one device-wide SQLite file, `damdam-safety.sqlite`, and `pending()`
returned every queued row regardless of who was signed in. Sign-out cleared only
the Keychain, and the sync timer kept running. The result is the original review
finding 1: user A queues an event offline, signs out, user B signs in, and A's
event is POSTed with B's token — and because the server derives the owner from
that token, the record is genuinely created as B's.

Server-side scoping cannot detect this. The fix is client-side.

### What changed

- Both outbox tables carry `owner_user_id`. Rows are written with it, read with
  `WHERE owner_user_id = ?`, and removed and updated only when the owner matches.
- Queuing without an owner is refused rather than defaulted.
- Rows left by a build that recorded no owner are **quarantined**, not adopted:
  they move to `<table>_quarantine` with a timestamp and a reason. They are kept
  — they are a user's data — and are never attributed to whoever signs in next.
  Quarantine is idempotent, so an interrupted migration converges.
- `CheckInSyncService` and `SOSSyncService` take a required `OutboxOwnership`
  with a `currentOwnerUserId()` **function**. Ownership is re-checked before the
  loop, before each send, and again after each send resolves, so an account
  switch mid-flight cannot confirm or consume a row. A delayed response for a
  departed account leaves the row in place for its rightful owner.
- `PersistedSession`, `ActiveSession` and `AuthenticatedMobileSession` carry
  `userId`.

### Deliberate consequence

A session persisted **before** this change has no `userId`, so it owns nothing:
its queues stay inert and it cannot enqueue new events. That is the correct
failure direction — these features are being retired, and an event that cannot
be attributed to an account must not be sent. It is recorded here because it is
a real behavior change for an existing install, not an oversight.

### Testing

`src/services/outboxAccountIsolation.test.ts` covers AC-30.4 against a **real
SQLite engine** (sql.js), because the defect lives in what the table records and
what the query filters — an array double would pass a broken schema. It covers
the account switch, process restart, delayed callback, signed-out state, timer
cancellation, quarantine and cross-account read/remove attempts.

### Still open

This subchunk isolates the queues; it does not retire them. The screens,
services, API clients, native permissions and server routes are removed in
subchunks 04B–04E — see
[`implementation/retirement/INVENTORY.md`](./implementation/retirement/INVENTORY.md).

---

## 8.11 Amendment — Retired Mobile Surface and Native Permissions (US-30, AC-30.5)

**Recorded 9 September 2026 by build chunk 04, subchunk 04C.**

Removed screens: `SosConfirm`, `SosSent`. Removed services: `checkInOutbox`,
`sosOutbox`, `outboxOwnership`, `checkInLocation`, `checkInBackground`,
`arrivalPrompts`, and the `testSqlite` test adapter. Removed API clients:
`checkInClient`, `sosClient`, `familyContactClient`, `emergencyContactClient`.
Removed component: `EmergencyEssentials`, with the section it occupied on the
eSIM QR screen. Home keeps its balances, banner and support handoff, and loses
the check-in button, the SOS button, the queue indicator and the last-check-in
line.

**Subchunk 04A's account-scoped queues are removed here, not undone.** 04A was
the "isolate" half of the inventory's *isolate first, retire second* sequence:
it makes an installed build safe for the accounts already using it, and this
removes the queue so the risk cannot recur. The AC-30.4 evidence stands as the
record for that transition.

`arrivalPrompts.ts` is split rather than deleted. Arrival geofencing retires
with the Hajj framing, but the eSIM activation deep link, push installation and
the date-based activation banner do not depend on it — they are now
`services/activationLinks.ts`. The banner was always permission-free: it keys on
the departure date, never on the device's location.

### Native permissions

Android drops `ACCESS_FINE_LOCATION` and `ACCESS_BACKGROUND_LOCATION`, the
`ArrivalGeofenceReceiver` registration, and the `play-services-location`
dependency that only the geofence client used. iOS drops
`NSLocationWhenInUseUsageDescription` and
`NSLocationAlwaysAndWhenInUseUsageDescription`.

`READ_CONTACTS`, `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS` and the `voip`
background mode belong to app calling and are removed with it in 04D.
`WRITE_EMBEDDED_SUBSCRIPTIONS`, `POST_NOTIFICATIONS`, `INTERNET`,
`ACCESS_NETWORK_STATE` and the euicc/telephony features are retained.

The native module is still registered as `ArrivalPromptModule` although it now
only fetches an FCM token. Renaming it needs an Android build to verify, which
this change does not run.

`src/featureRetirement.test.ts` walks the shipped source and fails on any
surviving import of a retired module, any code opening the retired queue
database, and any reintroduced permission.

### Device-local data is left in place

The retired `damdam-safety.sqlite` file is **not** deleted from devices. It may
hold queued rows and 04A's quarantine table, both of which are personal data,
and deleting it is exactly the irreversible step
[SCOPE-DISPOSITION.md](implementation/SCOPE-DISPOSITION.md) gates on the founder
decision. Nothing reads or writes it any more; its removal is owed by the
retention plan in 04E.

---

## 8.12 Amendment — App Calling and Caller-ID Verification Are Removed (US-30, AC-30.5)

**Recorded 9 September 2026 by build chunk 04, subchunk 04D.**

Removed screens: `DialPad`, `ActiveCall`, and the four `CliVerification`
screens. Removed services: `callKit`, `voiceGateway`, `deviceContacts`. Removed
API clients: `cliClient`, `voiceClient`. Removed util: `cliPhoneNumber`. Home
loses its call entry point. The `safety` locale namespace and the retired
`dial`, `callerId` and `activeCall` sections of `home` are deleted in both
English and French.

Native calling is removed in full rather than half:

- **Android** drops `READ_CONTACTS`, `RECORD_AUDIO`, `MODIFY_AUDIO_SETTINGS`,
  `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_PHONE_CALL`, the
  `CallHeadlessTaskService`, and the `io.wazo.callkeep.VoiceConnectionService`
  declaration. `DamDamFirebaseMessagingService` no longer routes incoming-call
  payloads.
- **iOS** drops `NSContactsUsageDescription`,
  `NSMicrophoneUsageDescription`, the whole `UIBackgroundModes` array
  (`voip` and `audio`), `VoipCallKitBridge.{h,m}`, and the PushKit registration
  and `PKPushRegistryDelegate` conformance in `AppDelegate.swift`.
- **Dependencies** drop `react-native-callkeep`,
  `react-native-voip-push-notification`, `react-native-contacts` and
  `@telnyx/react-voice-commons-sdk`, and the Jest mocks that existed only for
  them.

**Half-removing this would have been a defect, not a smaller change.** The
AppDelegate called `registerVoipPushes()` at launch; leaving that while removing
the `voip` background mode would ship an app registering for a push type it no
longer declares. The npm packages had to go with it, because the native bridge
included `RNCallKeep/RNCallKeep.h` and `RNVoipPushNotificationManager.h`
directly.

The remaining Android permissions are `INTERNET`,
`WRITE_EMBEDDED_SUBSCRIPTIONS`, `POST_NOTIFICATIONS` and
`ACCESS_NETWORK_STATE`, plus the euicc/telephony feature declarations. iOS
declares no usage description for any retired feature and no background mode.

**Neither native build was run.** No macOS runner and no Android build is
available in this environment, so the Xcode project edit (six references to the
removed bridge files) and the manifest and Gradle changes are reviewed source
changes, not verified builds. The screenshot jobs are the first place they run.

---

## 8.13 Amendment — Device State Belongs to an Account (US-29)

**Recorded 10 September 2026 by build chunk 06.**

### The defect

`utils/pinLocalStore.ts` wrote the unlock PIN to a **device-wide** Keychain
service with no account attached, and `clearPinLocally` was called from nowhere
in production — only from its own test. Every session-ending path in
`useSessionGate` called `clearSession()`, which resets the session entry alone.

So: A sets a PIN. A's session ends — expiry, sign-out, or a refresh token the
server rejected. B signs in on the same handset. B's unlock screen validates
against **A's PIN**, and A's failed-attempt lockout applies to B.

This is the same shape of defect chunk 04A found in the offline queues: state
scoped to a *device* rather than to the *account* that created it.

### The rule

**Anything persisted on the device that belongs to a signed-in account carries
that account's id, and every read is checked against the account asking.**

- `LocalPinState` gains a required `userId`. A record whose owner does not match
  reads as absent, so it can neither authenticate nor lock out the wrong person.
- A record with **no** owner predates this amendment and is also treated as
  absent, rather than adopted by whoever is signed in now.
- The eSIM compatibility-warning dismissal remains device-scoped. It describes
  the handset, not an account, and AC-10.6 requires it once per device.
- `clearAccountScopedState()` clears the account PIN and is called from **every**
  session-ending path in `useSessionGate`.
- A session persisted before US-29 has no `userId`, so `App.tsx` does not render
  the PIN gate for it at all; that session falls through to OTP sign-in rather
  than unlocking against an unattributable PIN.

`AuthenticatedMobileSession.userId` stays optional, because a session stored by
an older build genuinely may not have one. The `activated` onboarding step's
`userId` is now **required** — it is constructed in exactly one place and always
from `result.user.id`, so the optional type was simply inaccurate.

### Enforcement

`utils/accountScopedState.test.ts` asserts the account boundary directly: A's
PIN does not verify for B, B sees no stored PIN and no lockout, and ending a
session clears the store. Any future device-persisted state belongs in
`clearAccountScopedState()` and should be tested the same way.
